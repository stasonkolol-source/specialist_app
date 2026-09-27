// Заглушка support.js холста design-canvas (оригинал отдаёт хост холста, в репозитории его нет).
// Нужно ровно то, что влияет на рендер: содержимое <helmet> — в <head>, <x-dc> — обычный блок.
(function () {
  customElements.define(
    'x-dc',
    class extends HTMLElement {
      connectedCallback() {
        this.style.display = 'block';
      }
    },
  );
  function hoist() {
    for (const helmet of Array.from(document.querySelectorAll('helmet'))) {
      for (const el of Array.from(helmet.children)) document.head.appendChild(el);
      helmet.remove();
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', hoist);
  else hoist();
})();
