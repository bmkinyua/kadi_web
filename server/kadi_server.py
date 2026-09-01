#!/usr/bin/env python3
"""
KADI - Internet Multiplayer server.

Standalone, always-on program. Players never run this themselves --
one instance runs on a persistent, publicly reachable machine, and
every player's game client makes an OUTBOUND TCP connection to it (see
scenes.InternetMenuScene / InternetLobbyScene in the game client). This
is what sidesteps NAT/port-forwarding entirely: since host and joiners
alike only ever connect outward to this one known address, nobody but
this server ever needs to accept an inbound connection.

Responsibilities (full design writeup in server/README.md):
  1. LOBBY / MATCHMAKING (server/lobby.py, server/game_room.py):
     tracks open hosted games so browsing/joining players can pick one.
  2. GAME AUTHORITY: for each active game, runs the real
     core.game_manager.GameManager (completely unmodified) as the SOLE
     authority -- every player, host included, is a thin client here,
     never able to see another player's hand.

Run:
    python3 -m server.kadi_server [--port 52010]

Requires only the Python standard library plus this project's own
core/ and network/ modules -- no pygame -- so it runs headless on a
bare Linux box with just python3 installed.
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import AIDifficulty, MIN_PLAYERS, VERSION
from server.connection import ConnectionManager, DEFAULT_PORT
from server.lobby import Lobby
from server.game_room import GameRoom
from server.leaderboard_store import LeaderboardStore, LEADERBOARD_FILENAME

TICK_HZ = 20.0
TICK_DT = 1.0 / TICK_HZ


class KadiServer:
    def __init__(self, port: int = DEFAULT_PORT, ws_port: Optional[int] = None,
                 leaderboard_path: Optional[str] = None):
        # ws_port=None means "auto: port + 1000" so every existing
        # call site that only ever varied `port` -- including this
        # project's own test suite, which follows a PORT / PORT+1 /
        # PORT+2 convention for running several KadiServer instances
        # in one file to avoid collisions -- keeps working unchanged:
        # +1000 sits comfortably clear of that small-offset convention
        # rather than colliding with it (an earlier +1 default did
        # exactly that and broke test_internet_phase1_lobby.py).
        # Pass ws_port=0 explicitly to disable the WS listener
        # entirely (e.g. a LAN-only deployment).
        if ws_port is None:
            ws_port = port + 1000
        elif ws_port == 0:
            ws_port = None
        self.conns = ConnectionManager(port=port, ws_port=ws_port)
        self.lobby = Lobby()
        # Same directory this module lives in by default -- this is a
        # standalone, always-on server process (see this module's own
        # docstring), so "next to the server code" is the one sensible
        # default location; --leaderboard-path lets an operator point
        # it elsewhere (e.g. a persistent volume) without editing code.
        if leaderboard_path is None:
            leaderboard_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), LEADERBOARD_FILENAME)
        self.leaderboard = LeaderboardStore(leaderboard_path)

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        self.conns.start()

    def stop(self):
        self.conns.stop()

    def run_forever(self):
        self.start()
        ws_note = f", WebSocket on port {self.conns.ws_port}" if self.conns.ws_port else " (WebSocket listener disabled)"
        print(f"KADI Internet Multiplayer server listening on port {self.conns.port}{ws_note} "
              f"(Ctrl+C to stop)")
        try:
            while True:
                started = time.time()
                self.tick(TICK_DT)
                elapsed = time.time() - started
                time.sleep(max(0.0, TICK_DT - elapsed))
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.stop()

    # ── one server tick ──────────────────────────────────────────────────
    def tick(self, dt: float):
        for conn_id, msg in self.conns.poll():
            self._handle_message(conn_id, msg)

        now = time.time()
        for room in self.lobby.all_rooms():
            if not room.started or room.closed:
                continue
            room.check_disconnect_timeouts(now)
            room.tick(dt)
            self._broadcast_room_state(room)
            if room.gm.state.name == 'GAME_OVER':
                # Global leaderboard win-count increment (Part B) --
                # happens right here, at the exact point the server's
                # own authoritative GameManager already knows the true
                # winner, same "fire exactly once per finished game"
                # requirement game_manager.finalize_profile_stats has
                # for the local profile, reused via LeaderboardStore's
                # own game_id guard rather than trusting this being
                # called only once (see that module's docstring).
                name = room.winner_name()
                if name:
                    winner_conn_id = room.winner_conn_id()
                    winner_conn = self.conns.get_conn(winner_conn_id) if winner_conn_id is not None else None
                    identity_key = (winner_conn.external_id if winner_conn else None) or name
                    self.leaderboard.record_win(identity_key, name, room.gm.game_id)
                # The final state_sync already carries everything a
                # client needs (winner_id/finish_order_ids) -- no
                # reconnect/resume is in scope (see server/README.md),
                # so the room can be dropped immediately rather than
                # lingering.
                room.closed = True
                self.lobby.remove(room.game_id)

    def _broadcast_room_state(self, room: GameRoom):
        events = room.take_pending_events()
        for conn_id in room.conn_ids():
            snap = room.snapshot_for(conn_id, events)
            if snap is not None:
                self.conns.send_to(conn_id, snap)

    def _handle_message(self, conn_id: int, msg: dict):
        t = msg.get('type')
        if t == '_connected':
            return
        if t == '_disconnected':
            self._handle_disconnect(conn_id)
            return

        conn = self.conns.get_conn(conn_id)
        if conn is None:
            return  # connection already gone

        if t == 'hello':
            name = str(msg.get('name') or f"Player{conn_id}")[:24]
            self.conns.set_name(conn_id, name)
            # Optional, WEB CLIENTS ONLY: a stable per-platform identity
            # (see server/leaderboard_store.py's identity-key docstring
            # for what this does and doesn't guarantee -- notably, this
            # is NOT yet verified against the platform, just recorded).
            # The desktop TCP client never sends these, so `external_id`
            # simply stays None for it and nothing here changes for
            # that path.
            platform = msg.get('platform')
            raw_external_id = msg.get('external_id')
            external_id = None
            if isinstance(platform, str) and isinstance(raw_external_id, (str, int)) and str(raw_external_id):
                external_id = f"{platform[:24]}:{str(raw_external_id)[:64]}"
            self.conns.set_external_id(conn_id, external_id)
            return

        room = self.lobby.room_for_conn(conn_id)

        if t == 'list_games':
            self.conns.send_to(conn_id, {'type': 'games_list',
                                         'games': self.lobby.open_games_summary()})
            return

        if t == 'get_leaderboard':
            # Extension of the existing protocol (new message types on
            # the same already-open connection/port), not a second
            # network channel -- see the task's READ FIRST section for
            # why. Works from anywhere a connection is live (browse
            # lobby, waiting room, or mid-game) -- there's no reason to
            # gate this on room state the way in-game intents are.
            n = msg.get('n', 20)
            try:
                n = max(1, min(int(n), 50))
            except (TypeError, ValueError):
                n = 20
            entries = [{'name': name, 'wins': wins} for name, wins in self.leaderboard.top(n)]
            self.conns.send_to(conn_id, {'type': 'leaderboard_result', 'entries': entries})
            return

        if t == 'get_my_rank':
            # Keyed off this connection's OWN identity: its stable
            # platform id when it has one (see 'hello' above), falling
            # back to its current display name otherwise -- exactly
            # mirrors the key record_win() below uses, so a connection
            # always finds the same entry it contributes to. There's
            # still no account to look up instead (see
            # server/leaderboard_store.py's docstring).
            identity_key = conn.external_id or conn.name
            rank_info = self.leaderboard.rank_for(identity_key)
            if rank_info is None:
                self.conns.send_to(conn_id, {'type': 'my_rank_result', 'rank': None, 'wins': 0})
            else:
                rank, wins = rank_info
                self.conns.send_to(conn_id, {'type': 'my_rank_result', 'rank': rank, 'wins': wins})
            return

        if t == 'create_game':
            if room is not None:
                return  # already in a room -- ignore a duplicate create
            settings = msg.get('settings') or {}
            new_room = self.lobby.create_game(conn_id, conn.name, settings)
            self.conns.set_room(conn_id, new_room.game_id)
            self.conns.send_to(conn_id, {'type': 'welcome', 'player_id': conn_id,
                                         'game_id': new_room.game_id,
                                         'host_id': new_room.host_conn_id,
                                         'reconnect_token': new_room.token_for(conn_id),
                                         'server_version': VERSION})
            self._broadcast_lobby_state(new_room)
            return

        if t == 'join_game':
            if room is not None:
                return
            game_id = msg.get('game_id')
            target = self.lobby.get(game_id)
            if target is None or target.started or target.closed:
                self.conns.send_to(conn_id, {'type': 'reject',
                                             'reason': 'That game is no longer available.'})
                return
            if not target.add_member(conn_id, conn.name):
                self.conns.send_to(conn_id, {'type': 'reject', 'reason': 'Game is full.'})
                return
            self.conns.set_room(conn_id, target.game_id)
            self.conns.send_to(conn_id, {'type': 'welcome', 'player_id': conn_id,
                                         'game_id': target.game_id,
                                         'host_id': target.host_conn_id,
                                         'reconnect_token': target.token_for(conn_id),
                                         'server_version': VERSION})
            self._broadcast_lobby_state(target)
            return

        if t == 'rejoin_game':
            # A fresh connection (new conn_id -- the old socket is
            # already gone) presenting a token from an earlier
            # 'welcome'/'rejoined', trying to resume a match that's
            # already running before its grace period runs out. See
            # server/game_room.GameRoom.reconnect for what actually
            # makes this succeed or fail.
            game_id = msg.get('game_id')
            token = msg.get('token')
            target = self.lobby.get(game_id)
            if target is None or target.closed:
                self.conns.send_to(conn_id, {'type': 'reject',
                                             'reason': 'That game is no longer available.'})
                return
            if not target.reconnect(conn_id, token):
                self.conns.send_to(conn_id, {'type': 'reject',
                                             'reason': 'Could not reconnect — you may have '
                                                       'been removed from the match.'})
                return
            self.conns.set_room(conn_id, target.game_id)
            self.conns.set_name(conn_id, target.member_names.get(conn_id, conn.name))
            self.conns.send_to(conn_id, {'type': 'rejoined', 'player_id': conn_id,
                                         'game_id': target.game_id,
                                         'host_id': target.host_conn_id,
                                         'reconnect_token': token})
            return

        if t == 'request_start_game':
            if room is None or room.started:
                return
            if not room.is_host(conn_id):
                self.conns.send_to(conn_id, {'type': 'reject',
                                             'reason': 'Only the host can start the game.'})
                return
            extra_ai = self._ai_configs_from_settings(room.settings)
            err = room.start_game(extra_ai_configs=extra_ai)
            if err:
                self.conns.send_to(conn_id, {'type': 'reject', 'reason': err})
                return
            for c in room.conn_ids():
                self.conns.send_to(c, {'type': 'start_game'})
            self._broadcast_room_state(room)
            return

        if t == 'chat':
            # Works both pre-start (lobby banter) and mid-game — just a
            # relay, no game-state implications, so it doesn't need
            # room.started gating the way real intents do below. Text
            # only; a fixed emoji is just another short string in the
            # same 'text' field (see scenes.GameplayScene's quick-emoji
            # buttons) rather than a separate message shape.
            if room is None:
                return
            text = str(msg.get('text') or '').strip()[:200]
            if not text:
                return
            payload = {'type': 'chat', 'from': conn.name, 'text': text}
            for c in room.conn_ids():
                if c == conn_id:
                    continue  # sender already shows their own message locally (see
                              # network/client_state.ClientGameManager.send_chat)
                self.conns.send_to(c, payload)
            return

        # Anything else is an in-game intent -- only meaningful once
        # the room this connection belongs to has actually started.
        if room is not None and room.started:
            room.handle_intent(conn_id, msg)

    def _ai_configs_from_settings(self, settings: dict) -> list:
        ai_count = int(settings.get('ai_count', 0) or 0)
        if ai_count <= 0:
            return []
        diff_name = str(settings.get('ai_difficulty', 'MEDIUM')).upper()
        try:
            difficulty = AIDifficulty[diff_name]
        except KeyError:
            difficulty = AIDifficulty.MEDIUM
        names = ["Kadi-Bot", "Smart AI", "Trickster", "Blitz", "Shadow", "Rogue"]
        return [{'name': names[i % len(names)], 'is_human': False, 'difficulty': difficulty}
               for i in range(ai_count)]

    def _broadcast_lobby_state(self, room: GameRoom):
        msg = {'type': 'lobby_state', 'players': room.roster(),
              'host_id': room.host_conn_id,
              'game_name': room.display_name(),
              'settings': {'rows': [list(row) for row in room.settings_summary_rows()]}}
        for conn_id in room.conn_ids():
            self.conns.send_to(conn_id, msg)

    def _remove_from_room(self, conn_id: int, room: GameRoom):
        was_host = room.is_host(conn_id)
        room.remove_member(conn_id)
        self.conns.set_room(conn_id, None)
        if was_host or not room.member_names:
            # Host leaving (or the room emptying out) before the game
            # started ends the room outright -- nobody else can start
            # someone else's hosted game, and an empty room serves no
            # purpose sitting in the browse list. No host handoff /
            # reconnect is in scope for this pass (see
            # server/README.md's "Known limitations").
            room.closed = True
            for c in room.conn_ids():
                self.conns.send_to(c, {'type': 'room_closed',
                                       'reason': 'The host left the lobby.'})
            self.lobby.remove(room.game_id)
        else:
            self._broadcast_lobby_state(room)

    def _handle_disconnect(self, conn_id: int):
        room = self.lobby.room_for_conn(conn_id)
        if room is None:
            return
        if not room.started:
            self._remove_from_room(conn_id, room)
        else:
            # Mid-game disconnect: give them DISCONNECT_GRACE_SECONDS to
            # reconnect (a 'rejoin_game' with their token -- see
            # server/game_room.py) before check_disconnect_timeouts()
            # (called every tick, above) force-removes the seat via
            # GameManager.force_remove_player. Until then the round
            # just keeps going without them, same as any other
            # unresponsive player.
            room.mark_disconnected(conn_id, time.time())


def main():
    parser = argparse.ArgumentParser(description="KADI Internet Multiplayer server")
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f"TCP port to listen on (default {DEFAULT_PORT})")
    parser.add_argument('--ws-port', type=int, default=None,
                        help="WebSocket port for browser-based clients "
                             "(Discord/Telegram/WeChat/web-pwa) to listen on. "
                             "Default: --port + 1. Pass 0 to disable the WS "
                             "listener entirely (e.g. a LAN-only deployment).")
    parser.add_argument('--leaderboard-path', type=str, default=None,
                        help="Path to the global leaderboard JSON file "
                             "(default: leaderboard.json next to this script)")
    args = parser.parse_args()
    server = KadiServer(port=args.port, ws_port=args.ws_port, leaderboard_path=args.leaderboard_path)
    server.run_forever()


if __name__ == '__main__':
    main()
