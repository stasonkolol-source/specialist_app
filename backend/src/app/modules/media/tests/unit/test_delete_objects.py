"""Очистка multipart: только отсутствующая загрузка считается уже отменённой."""

from unittest.mock import AsyncMock

import pytest

from app.modules.media.application.dto import DeleteObjectsPayload, StoredRef
from app.modules.media.tasks import delete_objects
from app.platform.kernel.ids import MediaId, new_id
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError

pytestmark = pytest.mark.unit


@pytest.fixture
def payload() -> DeleteObjectsPayload:
    return DeleteObjectsPayload(
        media_id=MediaId(new_id()),
        objects=(StoredRef(bucket=Bucket.INCOMING, key="portfolio/original"),),
        upload_id="upload-1",
    )


@pytest.mark.parametrize("code", ["AccessDenied", "SignatureDoesNotMatch", "RequestTimeTooSkewed"])
async def test_abort_failure_is_not_reported_as_success(
    payload: DeleteObjectsPayload, code: str
) -> None:
    storage = AsyncMock(spec=StoragePort)
    storage.abort_multipart.side_effect = StorageRejectedError(code)

    with pytest.raises(StorageRejectedError, match=code):
        await delete_objects(payload, storage)

    storage.delete.assert_not_awaited()

    storage.abort_multipart.side_effect = None
    await delete_objects(payload, storage)

    assert storage.abort_multipart.await_count == 2
    storage.delete.assert_awaited_once_with(Bucket.INCOMING, "portfolio/original")


async def test_missing_multipart_still_deletes_the_original(payload: DeleteObjectsPayload) -> None:
    storage = AsyncMock(spec=StoragePort)
    storage.abort_multipart.side_effect = StorageRejectedError("NoSuchUpload")

    await delete_objects(payload, storage)

    storage.abort_multipart.assert_awaited_once_with(
        Bucket.INCOMING, "portfolio/original", upload_id="upload-1"
    )
    storage.delete.assert_awaited_once_with(Bucket.INCOMING, "portfolio/original")
