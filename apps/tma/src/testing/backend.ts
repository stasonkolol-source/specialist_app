// Общее фейков backend (ProfileBackend, MediaBackend): ответ и ошибка RFC 9457.

/** Ответ backend: тело и статус; ошибки — RFC 9457 с `code`. */
export interface BackendReply {
  status: number;
  body: unknown;
}

export const problem = (
  status: number,
  code: string,
  extra: Record<string, unknown> = {},
): BackendReply => ({
  status,
  body: { type: 'about:blank', title: code, status, code, trace_id: 'test', ...extra },
});
