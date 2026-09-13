import { WebAdapter } from '../../WebAdapter.js';

// Simulates a corrupted/partially-written profile blob (e.g. a crash
// mid-write, or a manual devtools edit) -- written directly, bypassing
// saveProfile(), since saveProfile() itself can only ever produce
// valid JSON. Mirrors read-after-corrupt-write.ts's settings version.
localStorage.setItem('kadi.web.profile', '{not valid json');

const adapter = new WebAdapter();
const loaded = await adapter.getProfile();
console.log('RESULT:' + JSON.stringify(loaded));
