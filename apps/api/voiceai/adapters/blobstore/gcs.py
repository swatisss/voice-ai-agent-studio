"""Adapter: the blob-store port backed by a Cloud Storage bucket.

Spec: /architecture/media-storage.md

For when the service is scaled past one instance. The SDK is imported lazily, like the LLM wire
adapters, so a deployment that never selects this adapter never loads it - and selecting it
without a bucket is a start-up error naming the missing setting rather than a silent fall back to
a local path (MS-01).
"""
from __future__ import annotations

import asyncio

from voiceai.ports.blobstore import BlobStoreUnavailable


def build(bucket: str | None) -> GcsBlobStore:
    if not bucket:
        raise BlobStoreUnavailable("MEDIA_BUCKET must be set when MEDIA_BACKEND=gcs")
    return GcsBlobStore(bucket)


class GcsBlobStore:
    def __init__(self, bucket: str) -> None:
        self.bucket_name = bucket
        self._bucket = None

    def _get_bucket(self):  # noqa: ANN202 - the SDK's type, loaded lazily
        if self._bucket is None:
            try:
                from google.cloud import storage  # type: ignore[import-not-found]
            except ImportError as exc:
                raise BlobStoreUnavailable(
                    "MEDIA_BACKEND=gcs needs google-cloud-storage installed"
                ) from exc
            self._bucket = storage.Client().bucket(self.bucket_name)
        return self._bucket

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        def _upload() -> None:
            self._get_bucket().blob(key).upload_from_string(data, content_type=content_type)

        await asyncio.to_thread(_upload)

    async def get(self, key: str) -> bytes | None:
        def _download() -> bytes | None:
            blob = self._get_bucket().blob(key)
            return blob.download_as_bytes() if blob.exists() else None

        return await asyncio.to_thread(_download)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            self._get_bucket().blob(key).delete(if_generation_match=None)

        try:
            await asyncio.to_thread(_delete)
        except Exception:  # noqa: BLE001 - deleting what is already gone is not an error
            return
