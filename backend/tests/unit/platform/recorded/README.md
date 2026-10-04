# Записанные ответы AI-провайдеров

Тела ответов для контрактных тестов адаптеров (`test_ai_adapters.py`, DEVELOPMENT_PLAN 2.4).
Пока ключей нет (K25, K26), ответы собраны по документации провайдеров: форма тела,
имена полей и значения `stop_reason` — как в API. С ключами их перезаписывает
`make cli ARGS="ai-smoke --record tests/unit/platform/recorded"`: тесты должны остаться
зелёными на настоящих ответах.

- `openai_moderation_*.json` — `POST https://api.openai.com/v1/moderations`;
  `openai_moderation_flagged_image.json` — пример ответа на фото из руководства OpenAI по
  модерации (6.7): у фото оцениваются только `sexual`, `violence*` и `self-harm*`.
- `anthropic_*.json` — `POST https://api.anthropic.com/v1/messages` со structured outputs.
