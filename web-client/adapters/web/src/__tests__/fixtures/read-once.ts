import { WebAdapter } from '../../WebAdapter.js';

const adapter = new WebAdapter();
const loaded = await adapter.getSettings();
console.log('RESULT:' + JSON.stringify(loaded));
