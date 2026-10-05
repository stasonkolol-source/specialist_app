import { sosed } from '@sosed/config/eslint';
import tokens from '@sosed/design-tokens/tokens.json' with { type: 'json' };

export default sosed({
  root: import.meta.dirname,
  react: true,
  i18n: true,
  radii: Object.keys(tokens.radius),
});
