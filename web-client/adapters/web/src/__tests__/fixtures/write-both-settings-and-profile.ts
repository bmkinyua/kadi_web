import { WebAdapter } from '../../WebAdapter.js';
import { SAMPLE_A } from './sampleSettings.js';
import { SAMPLE_PROFILE_A } from './sampleProfile.js';

// Proves Settings and Profile genuinely use separate storage -- see
// PlatformAdapter.ts's getProfile()/saveProfile() docstring: a
// "Reset to Defaults" in Settings must never touch badges/stats, only
// guaranteed if they're truly separate objects, not two keys inside
// one an editor could accidentally merge back together later.
const adapter = new WebAdapter();
await adapter.saveSettings(SAMPLE_A);
await adapter.saveProfile(SAMPLE_PROFILE_A);
const settings = await adapter.getSettings();
const profile = await adapter.getProfile();
console.log('RESULT:' + JSON.stringify({ settings, profile }));
