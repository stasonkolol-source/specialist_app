"""Сборка модуля specialists для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.specialists.api import SpecialistsApi
from app.modules.specialists.application.facade import SpecialistsFacade
from app.modules.specialists.application.ports import ProfileQuery, ProfileRepository
from app.modules.specialists.application.use_cases.become_pro import BecomePro
from app.modules.specialists.application.use_cases.create_profile import CreateProfile
from app.modules.specialists.application.use_cases.edit_profile import EditProfile
from app.modules.specialists.application.use_cases.hide_profile import HideProfile
from app.modules.specialists.application.use_cases.mark_founding import MarkFounding
from app.modules.specialists.application.use_cases.reset_availability import ResetAvailability
from app.modules.specialists.application.use_cases.set_availability import SetAvailability
from app.modules.specialists.application.use_cases.set_profile_areas import SetProfileAreas
from app.modules.specialists.application.use_cases.set_profile_categories import (
    SetProfileCategories,
)
from app.modules.specialists.application.use_cases.show_profile import ShowProfile
from app.modules.specialists.application.use_cases.submit_profile import SubmitProfile
from app.modules.specialists.application.views import ProfileViews
from app.modules.specialists.infrastructure.queries import SqlProfileQuery
from app.modules.specialists.infrastructure.repositories import SqlProfileRepository


class SpecialistsProvider(Provider):
    """Провайдер модуля specialists: связывает порты с реализациями."""

    scope = Scope.REQUEST

    profiles = provide(SqlProfileRepository, provides=ProfileRepository)
    query = provide(SqlProfileQuery, provides=ProfileQuery)
    views = provide(ProfileViews)
    facade = provide(SpecialistsFacade, provides=SpecialistsApi)
    create_profile = provide(CreateProfile)
    edit_profile = provide(EditProfile)
    set_profile_categories = provide(SetProfileCategories)
    set_profile_areas = provide(SetProfileAreas)
    submit_profile = provide(SubmitProfile)
    hide_profile = provide(HideProfile)
    show_profile = provide(ShowProfile)
    become_pro = provide(BecomePro)
    set_availability = provide(SetAvailability)
    reset_availability = provide(ResetAvailability)
    mark_founding = provide(MarkFounding)
