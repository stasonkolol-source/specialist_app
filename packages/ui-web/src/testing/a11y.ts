// Проверка доступности в тестах компонентов. Контраст считает design-tokens (jsdom не рендерит цвета).
import axe from 'axe-core';

export async function a11yViolations(container: Element): Promise<string[]> {
  const result = await axe.run(container, {
    rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
  });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`);
}
