import { sosed } from './eslint.js';

export default [...sosed({ root: import.meta.dirname }), { ignores: ['test/fixture-app/**'] }];
