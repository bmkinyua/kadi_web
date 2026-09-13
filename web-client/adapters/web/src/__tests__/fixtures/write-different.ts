import { WebAdapter } from '../../WebAdapter.js';
import { SAMPLE_B } from './sampleSettings.js';

const adapter = new WebAdapter();
await adapter.saveSettings(SAMPLE_B);
console.log('RESULT:' + JSON.stringify(SAMPLE_B));
