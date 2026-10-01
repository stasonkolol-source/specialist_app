// Файлы media в памяти — как backend 2.1–2.2: загрузка одним PUT по ссылке, complete и обработка.
// Общий для MSW в Vitest (testing/msw.ts) и page.route в e2e (e2e/api.ts), как ProfileBackend.
// Ссылки — того же origin: PUT в «хранилище» — /storage/<id> (в e2e его принимает page.route, в
// Vitest транспорт подменён), варианты готового фото — /cdn/<id>/<вариант>.webp. Обработка — при
// первом чтении после complete (GET /media/{id} или работа портфолио): у backend она идёт сама.
import type { MediaOut, MediaRefOut, UploadIn, UploadOut } from '@sosed/api-client';

import type { BackendReply } from './backend.ts';
import { problem } from './backend.ts';

/** Когда «сервер» получил файл: даты в ответах не зависят от часов теста. */
const AT = '2026-10-01T12:00:00Z';

export class MediaBackend {
  readonly assets = new Map<string, MediaOut>();
  /** Чем закончится обработка следующих файлов: готово или отказ (не картинка, модерация). */
  outcome: 'ready' | 'rejected' = 'ready';

  /** Ответ на запрос `/media*`; null — запрос не к media. */
  handle(method: string, path: string, body: unknown): BackendReply | null {
    const resource = path.replace(/^\/api\/v1/, '');
    if (!resource.startsWith('/media')) return null;
    if (method === 'POST' && resource === '/media/uploads') return this.start(body as UploadIn);
    const complete = /^\/media\/uploads\/([^/]+)\/complete$/.exec(resource);
    if (method === 'POST' && complete?.[1]) return this.complete(complete[1]);
    const one = /^\/media\/([^/]+)$/.exec(resource);
    if (method === 'GET' && one?.[1]) return this.get(one[1]);
    if (method === 'DELETE' && one?.[1]) return this.remove(one[1]);
    return problem(404, 'not_found');
  }

  /** Как показать файл в работе портфолио или фото профиля; удалённого нет. */
  ref(id: string): MediaRefOut | null {
    const media = this.processed(id);
    if (!media || media.status === 'deleted') return null;
    return {
      id: media.id,
      kind: media.kind,
      status: media.status,
      placeholder: media.placeholder,
      variants: media.variants,
      video_url: media.video?.url ?? null,
      duration_ms: media.duration_ms,
    };
  }

  private start(body: UploadIn): BackendReply {
    const id = `0199cc00-0000-7000-8000-${String(this.assets.size + 1).padStart(12, '0')}`;
    this.assets.set(id, {
      id,
      kind: body.mime_type.startsWith('video/') ? 'video' : 'image',
      purpose: body.purpose,
      status: 'pending_upload',
      mime_type: body.mime_type,
      size_bytes: body.size_bytes,
      moderation_status: 'pending',
      created_at: AT,
      uploaded_at: null,
      preview_url: null,
      width: null,
      height: null,
      duration_ms: null,
      placeholder: null,
      variants: [],
      video: null,
      failure_reason: null,
    });
    const plan: UploadOut = {
      media_id: id,
      multipart: false,
      part_size: null,
      parts: [
        { part_number: null, url: `/storage/${id}`, headers: { 'Content-Type': body.mime_type } },
      ],
      expires_at: AT,
    };
    return { status: 201, body: plan };
  }

  /** Файл дошёл: `uploaded`; обработка — к следующему GET. */
  private complete(id: string): BackendReply {
    const media = this.assets.get(id);
    if (!media) return problem(404, 'media_not_found');
    const uploaded: MediaOut = { ...media, status: 'uploaded', uploaded_at: AT };
    this.assets.set(id, uploaded);
    return { status: 200, body: uploaded };
  }

  private get(id: string): BackendReply {
    const media = this.processed(id);
    if (!media || media.status === 'deleted') return problem(404, 'media_not_found');
    return { status: 200, body: media };
  }

  /** Файл после обработки: загруженный становится готовым или отклонённым. */
  private processed(id: string): MediaOut | null {
    const media = this.assets.get(id);
    if (media?.status !== 'uploaded') return media ?? null;
    const processed: MediaOut =
      this.outcome === 'rejected'
        ? { ...media, status: 'rejected', failure_reason: 'unreadable' }
        : {
            ...media,
            status: 'ready',
            moderation_status: 'approved',
            width: 1600,
            height: 1200,
            variants: (['thumb', 'md', 'lg'] as const).map((name, index) => ({
              name,
              url: `/cdn/${id}/${name}.webp`,
              width: [320, 800, 1600][index] ?? 320,
              height: [240, 600, 1200][index] ?? 240,
            })),
          };
    this.assets.set(id, processed);
    return processed;
  }

  private remove(id: string): BackendReply {
    const media = this.assets.get(id);
    if (media) this.assets.set(id, { ...media, status: 'deleted' });
    return { status: 204, body: null };
  }
}
