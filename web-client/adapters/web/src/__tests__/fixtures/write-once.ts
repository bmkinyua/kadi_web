import { WebAdapter } from '../../WebAdapter.js';
import { SAMPLE_A } from './sampleSettings.js';

const adapter = new WebAdapter();
await adapter.saveSettings(SAMPLE_A);
console.log('RESULT:' + JSON.stringify(SAMPLE_A));
