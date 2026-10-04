// MainButton, нарисованная в контенте: клиент без нативной кнопки и браузер (8.1). Над шторками
// (Sheet — z-40): нативная MainButton Telegram тоже поверх всего WebView.
import { useBottomButtonState, useInsets } from '@sosed/platform';
import { Button } from '@sosed/ui-web';

/** Высота области кнопки без нижнего safe area: контент не уходит под неё. */
export const BUTTON_AREA = 76;

export function ContentMainButton() {
  const main = useBottomButtonState('main');
  const insets = useInsets();
  return (
    <div
      className="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-lg bg-bg px-4 pt-3"
      style={{ paddingBottom: insets.bottom + 12 }}
    >
      <Button full disabled={!main.enabled} onClick={main.click}>
        {main.text}
      </Button>
    </div>
  );
}
