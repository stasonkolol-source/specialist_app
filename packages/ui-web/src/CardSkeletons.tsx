// Скелетоны карточек выдачи, полей формы и переписки (Skeletons.tsx — основа): отдельным модулем,
// чтобы Главная (первый экран) не качала скелетоны экранов, которые открывают позже.
import { cx } from './cx.ts';
import { Skeleton } from './Feedback.tsx';
import { SkeletonCard, SkeletonText } from './Skeletons.tsx';

/** Карточка специалиста в выдаче (SpecialistCard): аватар, имя, «коротко о себе», рейтинг и район,
 *  языки, бейдж и цена «от». */
export function SpecialistCardSkeleton() {
  return (
    <SkeletonCard tight>
      <div className="flex items-start gap-3">
        <Skeleton round className="size-12 shrink-0" />
        <div className="flex min-w-0 grow flex-col gap-0.5">
          <SkeletonText size="title" className="w-2/5" />
          <SkeletonText size="sm" className="w-4/5" />
          <SkeletonText size="cap" className="w-1/2" />
          <SkeletonText size="cap" className="w-1/3" />
        </div>
      </div>
      <div className="flex items-end justify-between gap-2">
        <Skeleton className="h-6 w-24" />
        <SkeletonText size="title" className="w-20" />
      </div>
    </SkeletonCard>
  );
}

/** Карточка заявки (JobCard): заголовок и бюджет, бейджи, начало описания, место и время,
 *  полоски мест своей строкой; `photos` — с превью фото. */
export function JobCardSkeleton({ photos = false }: { photos?: boolean }) {
  return (
    <SkeletonCard tight>
      <div className="flex items-start justify-between gap-3">
        <SkeletonText size="title" className="w-3/5" />
        <SkeletonText size="title" className="w-20" />
      </div>
      <div className="flex gap-1.5">
        <Skeleton className="h-6 w-28" />
        <Skeleton className="h-6 w-20" />
      </div>
      <div className="flex flex-col">
        <SkeletonText size="sm" className="w-full" />
        <SkeletonText size="sm" className="w-3/4" />
      </div>
      {photos && (
        <div className="flex gap-2">
          {[0, 1, 2].map((photo) => (
            <Skeleton key={photo} radius="field" className="size-14" />
          ))}
        </div>
      )}
      <div className="flex items-center justify-between gap-3">
        <SkeletonText size="cap" className="w-2/5" />
        <SkeletonText size="cap" className="w-16" />
      </div>
      <SkeletonText size="cap" className="w-1/2" />
    </SkeletonCard>
  );
}

/** Поле формы (.fld): подпись на фоне экрана и пустая рамка поля; `tall` — многострочное. */
export function FieldSkeleton({ tall = false }: { tall?: boolean }) {
  return (
    <div aria-hidden="true" className="flex flex-col gap-1.5">
      <SkeletonText size="sm" screen className="w-1/3" />
      <span
        className={cx(
          'block rounded-field border border-line bg-surface motion-safe:animate-pulse',
          tall ? 'h-26' : 'h-12',
        )}
      />
    </div>
  );
}

/** Пузыри переписки по низу (Bubble): собеседник слева на поверхности, свои справа — акцентом. */
const BUBBLES = [
  { out: false, className: 'h-10 w-3/5' },
  { out: true, className: 'h-10 w-1/2' },
  { out: false, className: 'h-16 w-2/3' },
  { out: true, className: 'h-10 w-2/5' },
] as const;

export function ChatSkeleton() {
  return (
    <div aria-hidden="true" className="flex flex-1 flex-col justify-end gap-2 p-3">
      {BUBBLES.map((bubble, index) => (
        <span
          key={index}
          className={cx(
            'block rounded-[18px] motion-safe:animate-pulse',
            bubble.out
              ? 'self-end rounded-br-[6px] bg-accent-soft'
              : 'self-start rounded-bl-[6px] bg-surface',
            bubble.className,
          )}
        />
      ))}
    </div>
  );
}
