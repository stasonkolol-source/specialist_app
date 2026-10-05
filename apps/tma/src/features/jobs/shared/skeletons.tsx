// Скелетоны экранов заявок по форме их карточек (S20, S23–S26): поверхность карточки, фигуры
// внутри — видны на фоне экрана в обеих темах (ui-web Skeletons.tsx).
import { FieldSkeleton, Skeleton, SkeletonCard, SkeletonText } from '@sosed/ui-web';

/** Своя заявка (S23): статус и срок, название, когда-где-бюджет, места и действия. */
export function JobSummarySkeleton() {
  return (
    <SkeletonCard>
      <div className="flex items-center justify-between gap-2">
        <Skeleton className="h-6 w-28" />
        <SkeletonText size="cap" className="w-20" />
      </div>
      <SkeletonText size="h2" className="w-4/5" />
      <div className="flex flex-col gap-2">
        <SkeletonText size="cap" className="w-1/2" />
        <SkeletonText size="cap" className="w-2/5" />
        <SkeletonText size="cap" className="w-3/5" />
      </div>
      <SkeletonText size="sm" className="w-2/3" />
      <div className="grid grid-cols-2 gap-2">
        <Skeleton radius="field" className="h-11" />
        <Skeleton radius="field" className="h-11" />
      </div>
    </SkeletonCard>
  );
}

/** Отклик исполнителя (S23, S24): аватар, имя и цена, рейтинг, сообщение и бейджи. */
export function OfferCardSkeleton() {
  return (
    <SkeletonCard tight>
      <div className="flex items-start gap-3">
        <Skeleton round className="size-12 shrink-0" />
        <div className="flex min-w-0 grow flex-col gap-1">
          <div className="flex items-start justify-between gap-2">
            <SkeletonText size="title" className="w-2/5" />
            <SkeletonText size="title" className="w-20" />
          </div>
          <SkeletonText size="cap" className="w-1/2" />
        </div>
      </div>
      <div className="flex flex-col">
        <SkeletonText size="sm" className="w-full" />
        <SkeletonText size="sm" className="w-3/4" />
      </div>
      <div className="flex gap-1.5">
        <Skeleton className="h-6 w-24" />
        <Skeleton className="h-6 w-20" />
      </div>
    </SkeletonCard>
  );
}

/** Мастер заявки S20a–d, пока черновик не пришёл из DeviceStorage (или правка — с сервера):
 *  шапка шага и форма шага, а не пустой экран. */
export function WizardSkeleton({ step }: { step: 1 | 2 | 3 | 4 }) {
  return (
    <section className="flex flex-col gap-4 px-4 pt-3 pb-6" aria-busy="true">
      <div aria-hidden="true" className="flex flex-col gap-2">
        <div className="flex gap-1.5">
          {[1, 2, 3, 4].map((bar) => (
            <Skeleton key={bar} screen className="h-1 flex-1" />
          ))}
        </div>
        <SkeletonText size="cap" screen className="w-1/2" />
      </div>
      <SkeletonText size="h2" screen className="w-3/5" />
      {step === 4 ? (
        // предпросмотр: карточка заявки с фото, сроком и местом, бюджетом
        <SkeletonCard>
          <SkeletonText size="h2" className="w-4/5" />
          <div className="flex gap-2">
            {[0, 1, 2].map((photo) => (
              <Skeleton key={photo} radius="field" className="size-18" />
            ))}
          </div>
          <SkeletonText size="sm" className="w-full" />
          <SkeletonText size="sm" className="w-2/3" />
          <SkeletonText size="title" className="w-1/3" />
        </SkeletonCard>
      ) : (
        <>
          <FieldSkeleton tall={step === 1} />
          {step === 3 && <Skeleton screen radius="field" className="h-10 w-full" />}
          <FieldSkeleton tall={step === 2} />
          {step === 1 && (
            <div className="flex gap-2">
              {[0, 1, 2].map((tile) => (
                <Skeleton key={tile} screen radius="field" className="size-18" />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
