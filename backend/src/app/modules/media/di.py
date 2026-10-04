"""Сборка модуля media для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.media.api import MediaApi, MediaModeration
from app.modules.media.application.config import MediaConfig
from app.modules.media.application.facade import MediaFacade, MediaModerator
from app.modules.media.application.ports import (
    ImageProcessor,
    MediaQuery,
    MediaRepository,
    UploadQuota,
    VideoProcessor,
)
from app.modules.media.application.queries import MediaQueries
from app.modules.media.application.use_cases.cleanup_orphans import CleanupOrphans
from app.modules.media.application.use_cases.complete_upload import CompleteUpload
from app.modules.media.application.use_cases.delete_media import DeleteMedia
from app.modules.media.application.use_cases.forget_owner import ForgetOwner
from app.modules.media.application.use_cases.hide_variants import (
    HideDeleted,
    HideVariants,
    RestoreVariants,
)
from app.modules.media.application.use_cases.process_media import ProcessMedia
from app.modules.media.application.use_cases.purge_deleted import PurgeDeleted
from app.modules.media.application.use_cases.retry_stuck import RetryStuck
from app.modules.media.application.use_cases.sign_upload_parts import SignUploadParts
from app.modules.media.application.use_cases.start_upload import StartUpload
from app.modules.media.infrastructure.imaging import SubprocessImageProcessor
from app.modules.media.infrastructure.queries import SqlMediaQuery
from app.modules.media.infrastructure.quota import ValkeyUploadQuota
from app.modules.media.infrastructure.repositories import SqlMediaRepository
from app.modules.media.infrastructure.video import FfmpegVideoProcessor
from app.platform.settings import S3Settings
from app.platform.storage.port import StoragePort


class MediaProvider(Provider):
    """Провайдер модуля media: связывает порты с реализациями."""

    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    def config(self, s3: S3Settings) -> MediaConfig:
        return MediaConfig(public_base_url=s3.public_base_url)

    @provide(scope=Scope.APP)
    def images(self) -> ImageProcessor:
        return SubprocessImageProcessor()

    @provide(scope=Scope.APP)
    def videos(self, storage: StoragePort) -> VideoProcessor:
        return FfmpegVideoProcessor(storage)

    assets = provide(SqlMediaRepository, provides=MediaRepository)
    query = provide(SqlMediaQuery, provides=MediaQuery)
    quota = provide(ValkeyUploadQuota, provides=UploadQuota)
    queries = provide(MediaQueries)
    facade = provide(MediaFacade, provides=MediaApi)
    moderator = provide(MediaModerator, provides=MediaModeration)
    start_upload = provide(StartUpload)
    sign_upload_parts = provide(SignUploadParts)
    complete_upload = provide(CompleteUpload)
    delete_media = provide(DeleteMedia)
    forget_owner = provide(ForgetOwner)
    cleanup_orphans = provide(CleanupOrphans)
    process_media = provide(ProcessMedia)
    purge_deleted = provide(PurgeDeleted)
    retry_stuck = provide(RetryStuck)
    hide_variants = provide(HideVariants)
    restore_variants = provide(RestoreVariants)
    hide_deleted = provide(HideDeleted)
