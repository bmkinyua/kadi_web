import { WebAdapter } from '../../WebAdapter.js';

// Simulates a corrupted/partially-written settings blob (e.g. a crash
// mid-write, or a manual devtools edit) -- written directly, bypassing
// saveSettings(), since saveSettings() itself can only ever produce
// valid JSON.
localStorage.setItem('kadi.web.settings', '{not valid json');

const adapter = new WebAdapter();
const loaded = await adapter.getSettings();
console.log('RESULT:' + JSON.stringify(loaded));
