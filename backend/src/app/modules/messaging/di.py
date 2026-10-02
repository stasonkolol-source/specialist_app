"""Сборка модуля messaging для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.messaging.api import MessagingApi
from app.modules.messaging.application.cards import ConversationCards
from app.modules.messaging.application.facade import MessagingFacade
from app.modules.messaging.application.ports import (
    ContactShares,
    ContactVerifier,
    ConversationQueries,
    ConversationRepository,
    MessageQuota,
    MessageStore,
    Presence,
)
from app.modules.messaging.application.use_cases.forget_messages import ForgetMessages
from app.modules.messaging.application.use_cases.list_conversations import ListConversations
from app.modules.messaging.application.use_cases.list_messages import ListMessages
from app.modules.messaging.application.use_cases.propose_deal import ProposeDeal
from app.modules.messaging.application.use_cases.purge_messages import PurgeMessages
from app.modules.messaging.application.use_cases.read_conversation import ReadConversation
from app.modules.messaging.application.use_cases.record_deal_event import RecordDealEvent
from app.modules.messaging.application.use_cases.send_message import SendMessage
from app.modules.messaging.application.use_cases.share_contact import ShareContact
from app.modules.messaging.application.use_cases.start_conversation import StartConversation
from app.modules.messaging.infrastructure.contacts import TelegramContactVerifier
from app.modules.messaging.infrastructure.presence import CachePresence
from app.modules.messaging.infrastructure.queries import SqlConversationQueries
from app.modules.messaging.infrastructure.quota import ValkeyMessageQuota
from app.modules.messaging.infrastructure.repositories import (
    SqlContactShares,
    SqlConversationRepository,
    SqlMessageStore,
)


class MessagingProvider(Provider):
    """Провайдер модуля messaging: связывает порты с реализациями."""

    scope = Scope.REQUEST

    conversations = provide(SqlConversationRepository, provides=ConversationRepository)
    messages = provide(SqlMessageStore, provides=MessageStore)
    shares = provide(SqlContactShares, provides=ContactShares)
    contact_verifier = provide(TelegramContactVerifier, provides=ContactVerifier)
    queries = provide(SqlConversationQueries, provides=ConversationQueries)
    quota = provide(ValkeyMessageQuota, provides=MessageQuota)
    presence = provide(CachePresence, provides=Presence)
    cards = provide(ConversationCards)
    facade = provide(MessagingFacade, provides=MessagingApi)
    """Фасад для модерации (адаптер цели `message`) и уведомлений (`message.received`)."""
    start_conversation = provide(StartConversation)
    send_message = provide(SendMessage)
    read_conversation = provide(ReadConversation)
    list_conversations = provide(ListConversations)
    list_messages = provide(ListMessages)
    propose_deal = provide(ProposeDeal)
    share_contact = provide(ShareContact)
    record_deal_event = provide(RecordDealEvent)
    forget_messages = provide(ForgetMessages)
    purge_messages = provide(PurgeMessages)
