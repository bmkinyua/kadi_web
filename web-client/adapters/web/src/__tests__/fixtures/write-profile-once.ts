import { WebAdapter } from '../../WebAdapter.js';
import { SAMPLE_PROFILE_A } from './sampleProfile.js';

const adapter = new WebAdapter();
await adapter.saveProfile(SAMPLE_PROFILE_A);
console.log('RESULT:' + JSON.stringify(SAMPLE_PROFILE_A));
