"""Сборка модуля media для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.media.application.ports import MediaQuery, MediaRepository, UploadQuota
from app.modules.media.application.queries import MediaQueries
from app.modules.media.application.use_cases.cleanup_orphans import CleanupOrphans
from app.modules.media.application.use_cases.complete_upload import CompleteUpload
from app.modules.media.application.use_cases.delete_media import DeleteMedia
from app.modules.media.application.use_cases.sign_upload_parts import SignUploadParts
from app.modules.media.application.use_cases.start_upload import StartUpload
from app.modules.media.infrastructure.queries import SqlMediaQuery
from app.modules.media.infrastructure.quota import ValkeyUploadQuota
from app.modules.media.infrastructure.repositories import SqlMediaRepository


class MediaProvider(Provider):
    """Провайдер модуля media: связывает порты с реализациями."""

    scope = Scope.REQUEST

    assets = provide(SqlMediaRepository, provides=MediaRepository)
    query = provide(SqlMediaQuery, provides=MediaQuery)
    quota = provide(ValkeyUploadQuota, provides=UploadQuota)
    queries = provide(MediaQueries)
    start_upload = provide(StartUpload)
    sign_upload_parts = provide(SignUploadParts)
    complete_upload = provide(CompleteUpload)
    delete_media = provide(DeleteMedia)
    cleanup_orphans = provide(CleanupOrphans)
