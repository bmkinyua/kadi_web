/**
 * KADI - web-pwa entry point.
 *
 * This is the ONLY file in the whole web-client tree that imports a
 * concrete adapter class (WebAdapter) or concrete MsomiStore backend
 * (via createMsomiStore()). Platform selection happens here, at
 * build/entry time -- see KADI_web_port_implementation_plan.md §2 --
 * not via runtime user-agent sniffing. A future
 * apps/discord-activity/src/main.ts would be this same handful of
 * lines, importing DiscordAdapter instead, and omitting the
 * createMsomiStore() call/argument entirely if that platform has no
 * local-filesystem-shaped storage concept (see index.ts's
 * bootstrapGame() header on why that argument is optional).
 */
import { WebAdapter, createMsomiStore } from '@kadi/adapter-web';
import { bootstrapGame } from '@kadi/renderer';

bootstrapGame(new WebAdapter(), 'game-root', createMsomiStore());
