import { sosed } from '@sosed/config/eslint';

export default sosed({ root: import.meta.dirname, react: true, i18n: true, appBoundaries: true });
