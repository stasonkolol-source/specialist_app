// Порядок «Моих заявок» S22 внутри группы: сначала то, где ждут решения клиента, — заявки с
// откликами (с новыми, ещё не открытыми, выше), потом на проверке или «нужно исправить», потом
// «Ждём откликов»; при равенстве новее выше. Иначе на 375×667 «3 отклика — выберите исполнителя»
// уходила под таббар, а первой стояла заявка, где делать нечего.
import type { JobOut } from '@sosed/api-client';

type Ordered = Pick<
  JobOut,
  'status' | 'responses_count' | 'new_responses' | 'published_at' | 'created_at'
>;

function rank(job: Ordered): number {
  if (job.status === 'published') {
    if (job.responses_count === 0) return 3;
    return (job.new_responses ?? 0) > 0 ? 0 : 1;
  }
  // черновик, на проверке, нужно исправить; в остальных группах важно только время
  return job.status === 'draft' || job.status === 'pending_moderation' || job.status === 'rejected'
    ? 2
    : 0;
}

const placedAt = (job: Ordered) => Date.parse(job.published_at ?? job.created_at);

export function byAttention(a: Ordered, b: Ordered): number {
  return rank(a) - rank(b) || placedAt(b) - placedAt(a);
}
