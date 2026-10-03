"""Сборка модуля deals для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.deals.api import DealsApi
from app.modules.deals.application.facade import DealsFacade
from app.modules.deals.application.ports import (
    DealQueries,
    DealRepository,
    DisputeQueries,
    DisputeRepository,
)
from app.modules.deals.application.use_cases.cancel_deal import CancelDeal
from app.modules.deals.application.use_cases.cancel_user_deals import CancelUserDeals
from app.modules.deals.application.use_cases.complete_deal import CompleteDeal
from app.modules.deals.application.use_cases.confirm_deal import ConfirmDeal
from app.modules.deals.application.use_cases.decline_deal import DeclineDeal
from app.modules.deals.application.use_cases.list_my_deals import ListMyDeals
from app.modules.deals.application.use_cases.open_dispute import OpenDispute
from app.modules.deals.application.use_cases.respond_dispute import RespondDispute
from app.modules.deals.application.use_cases.show_deal import ShowDeal
from app.modules.deals.application.use_cases.show_dispute import ShowDispute
from app.modules.deals.application.use_cases.sweep_deals import SweepDeals
from app.modules.deals.application.use_cases.sweep_disputes import SweepDisputes
from app.modules.deals.application.use_cases.withdraw_dispute import WithdrawDispute
from app.modules.deals.infrastructure.queries import SqlDealQueries, SqlDisputeQueries
from app.modules.deals.infrastructure.repositories import SqlDealRepository, SqlDisputeRepository


class DealsProvider(Provider):
    """Провайдер модуля deals: связывает порты с реализациями."""

    scope = Scope.REQUEST

    deals = provide(SqlDealRepository, provides=DealRepository)
    queries = provide(SqlDealQueries, provides=DealQueries)
    facade = provide(DealsFacade, provides=DealsApi)
    """Фасад для jobs: выбор отклика создаёт сделку в той же транзакции; для модерации — решение
    по спору в её транзакции."""
    show_deal = provide(ShowDeal)
    list_my_deals = provide(ListMyDeals)
    confirm_deal = provide(ConfirmDeal)
    decline_deal = provide(DeclineDeal)
    complete_deal = provide(CompleteDeal)
    cancel_deal = provide(CancelDeal)
    cancel_user_deals = provide(CancelUserDeals)
    sweep_deals = provide(SweepDeals)
    disputes = provide(SqlDisputeRepository, provides=DisputeRepository)
    dispute_queries = provide(SqlDisputeQueries, provides=DisputeQueries)
    open_dispute = provide(OpenDispute)
    respond_dispute = provide(RespondDispute)
    withdraw_dispute = provide(WithdrawDispute)
    show_dispute = provide(ShowDispute)
    sweep_disputes = provide(SweepDisputes)
