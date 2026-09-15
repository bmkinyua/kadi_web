import { WebAdapter } from '../../WebAdapter.js';

const adapter = new WebAdapter();
const loaded = await adapter.getProfile();
console.log('RESULT:' + JSON.stringify(loaded));
