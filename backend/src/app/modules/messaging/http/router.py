"""HTTP messaging (DEVELOPMENT_PLAN 6.3a; ARCHITECTURE §8.5, §11.5): переписка клиента и
исполнителя.

- `GET /conversations` — свои диалоги, свежие первыми: вторая сторона, последнее сообщение,
  непрочитанные;
- `POST /conversations {response_id | profile_id}` — начать (или открыть уже начатый) диалог:
  по отклику — клиент заявки или исполнитель отклика, напрямую — клиент специалисту; новый
  тратит часовой лимит (пять);
- `GET /conversations/{id}/messages?cursor&direction` — сообщения старые → новые: первая
  страница — последние, `direction=older` — более ранние, `direction=newer` — новые для поллинга
  S30; ETag по телу и 304;
- `POST /conversations/{id}/messages` — написать (`client_msg_id` — повтор не дублирует): до
  договорённости контакты в тексте скрыты; лимит 20 или 100 в час по уровню доверия;
- `POST /conversations/{id}/read` — дочитал до сообщения.

Чужой диалог — 404.
"""

import hashlib
from typing import Annotated, Final, Literal
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, Query, Request, Response, status

from app.modules.messaging.application.use_cases.list_conversations import (
    ListConversations,
    ListConversationsCommand,
)
from app.modules.messaging.application.use_cases.list_messages import (
    ListMessages,
    ListMessagesCommand,
)
from app.modules.messaging.application.use_cases.read_conversation import (
    ReadConversation,
    ReadConversationCommand,
)
from app.modules.messaging.application.use_cases.send_message import (
    SendMessage,
    SendMessageCommand,
)
from app.modules.messaging.application.use_cases.start_conversation import (
    StartConversation,
    StartConversationCommand,
)
from app.modules.messaging.http.schemas import (
    ConversationOut,
    ConversationsPageOut,
    ConversationStartIn,
    ConversationStartOut,
    MessageIn,
    MessageOut,
    MessagesPageOut,
    ReadIn,
)
from app.platform.http.caching import NOT_MODIFIED, matches
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.pagination import DEFAULT_LIMIT, PageRequest
from app.platform.kernel.principal import Principal

CONVERSATIONS_LIMIT: Final = 50
MESSAGES_LIMIT: Final = 100

router = APIRouter(tags=["messaging"])
ConversationPath = Annotated[UUID, Path(description="id диалога")]


@router.get("/conversations", response_model=ConversationsPageOut, dependencies=AUTHENTICATED)
@inject
async def list_conversations(
    *,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=CONVERSATIONS_LIMIT)] = DEFAULT_LIMIT,
    principal: FromDishka[Principal],
    conversations: FromDishka[ListConversations],
) -> ConversationsPageOut:
    """Свои диалоги, свежие первыми."""
    page = await conversations(
        ListConversationsCommand(
            actor_id=principal.user_id, page=PageRequest(cursor=cursor, limit=limit)
        )
    )
    return ConversationsPageOut(
        items=[ConversationOut.of(item, principal.user_id) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("/conversations", response_model=ConversationStartOut, dependencies=AUTHENTICATED)
@inject
async def start_conversation(
    body: ConversationStartIn,
    principal: FromDishka[Principal],
    start: FromDishka[StartConversation],
    response: Response,
) -> ConversationStartOut:
    """Начать диалог или открыть уже начатый: 201 — новый, 200 — был."""
    started = await start(
        StartConversationCommand(
            actor_id=principal.user_id, response_id=body.response_id, profile_id=body.profile_id
        )
    )
    response.status_code = status.HTTP_201_CREATED if started.created else status.HTTP_200_OK
    return ConversationStartOut(id=started.conversation_id, created=started.created)


@router.get(
    "/conversations/{conversation_id:uuid}/messages",
    response_model=MessagesPageOut,
    responses=NOT_MODIFIED,
    dependencies=AUTHENTICATED,
)
@inject
async def list_messages(
    *,
    conversation_id: ConversationPath,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    direction: Annotated[Literal["older", "newer"], Query()] = "older",
    limit: Annotated[int, Query(ge=1, le=MESSAGES_LIMIT)] = DEFAULT_LIMIT,
    request: Request,
    principal: FromDishka[Principal],
    messages: FromDishka[ListMessages],
) -> Response:
    """Сообщения диалога старые → новые; без изменений — 304 по ETag."""
    found = await messages(
        ListMessagesCommand(
            actor_id=principal.user_id,
            conversation_id=conversation_id,
            cursor=cursor,
            direction=direction,
            limit=limit,
        )
    )
    body = MessagesPageOut.of(found.conversation, found.page, principal.user_id)
    raw = body.model_dump_json().encode()
    etag = f'"{hashlib.sha256(raw).hexdigest()[:32]}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(raw, media_type="application/json", headers=headers)


@router.post(
    "/conversations/{conversation_id:uuid}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageOut,
    dependencies=AUTHENTICATED,
)
@inject
async def send_message(
    conversation_id: ConversationPath,
    body: MessageIn,
    principal: FromDishka[Principal],
    send: FromDishka[SendMessage],
) -> MessageOut:
    """Написать в диалог; до договорённости контакты скрыты."""
    message = await send(
        SendMessageCommand(
            actor_id=principal.user_id,
            trust_level=principal.trust_level,
            conversation_id=conversation_id,
            body=body.body,
            client_msg_id=body.client_msg_id,
        )
    )
    return MessageOut.of(message, principal.user_id)


@router.post(
    "/conversations/{conversation_id:uuid}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def read_conversation(
    conversation_id: ConversationPath,
    body: ReadIn,
    principal: FromDishka[Principal],
    read: FromDishka[ReadConversation],
) -> None:
    """Дочитал до сообщения: непрочитанные на S29 гаснут."""
    await read(
        ReadConversationCommand(
            actor_id=principal.user_id, conversation_id=conversation_id, message_id=body.message_id
        )
    )
