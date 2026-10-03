// Экран ещё грузится (его чанк, тексты, проверка входа) дольше PENDING_MS — тонкая полоса сверху
// под шапкой Telegram, чтобы нажатие не выглядело незамеченным. Оболочка с таббаром остаётся;
// скелетон экрана придёт с его чанком.
export function RoutePending() {
  return (
    <div aria-busy="true" className="h-0.5 w-full overflow-hidden">
      <div className="h-full w-full bg-accent motion-safe:animate-pulse" />
    </div>
  );
}
