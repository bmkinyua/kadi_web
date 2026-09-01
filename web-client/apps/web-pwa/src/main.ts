/**
 * KADI - web-pwa entry point.
 *
 * This is the ONLY file in the whole web-client tree that imports a
 * concrete adapter class (WebAdapter). Platform selection happens
 * here, at build/entry time -- see
 * KADI_web_port_implementation_plan.md §2 -- not via runtime
 * user-agent sniffing. A future apps/discord-activity/src/main.ts
 * would be this same four lines, importing DiscordAdapter instead.
 */
import { WebAdapter } from '@kadi/adapter-web';
import { bootstrapGame } from '@kadi/renderer';

bootstrapGame(new WebAdapter(), 'game-root');
