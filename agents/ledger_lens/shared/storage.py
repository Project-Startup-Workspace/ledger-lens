"""Where evidence files and case files live: local folders in development, Google Cloud
(Cloud Storage and Firestore) when deployed. Callers depend only on the protocols."""

import fcntl
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ledger_lens.shared.config import Backend, Settings
from ledger_lens.shared.schemas import CreditFile, utc_now

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")


class ConcurrentUpdateError(RuntimeError):
    """Someone else saved the case after it was loaded; reload and try again."""


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...


class CaseRepository(Protocol):
    def save(self, case: CreditFile) -> None:
        """Store the case if nobody saved it since it was loaded, then bump its revision.

        Raises ConcurrentUpdateError otherwise, so two writers never silently overwrite
        each other (the last-writer-wins problem across processes or instances).
        """
        ...

    def get(self, case_id: str) -> CreditFile | None: ...

    def list(self, limit: int = 50) -> list[CreditFile]:
        """Cases ordered by most recent update."""
        ...


def check_key(key: str) -> str:
    """Reject keys that could escape the store's root, such as '../x' or '/etc'."""
    if not _SAFE_KEY.match(key) or ".." in key.split("/"):
        raise ValueError(f"unsafe storage key {key!r}")
    return key


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._root / check_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return (self._root / check_key(key)).read_bytes()


class LocalCaseRepository:
    """One JSON file per case. Plenty for a laptop demo; Firestore when deployed."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, case: CreditFile) -> None:
        path = self._root / f"{check_key(case.case_id)}.json"
        with (self._root / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            stored = self.get(case.case_id)
            if stored is not None and stored.revision != case.revision:
                raise ConcurrentUpdateError(case.case_id)
            stored = case.model_copy(
                update={"revision": case.revision + 1, "updated_at": utc_now()}
            )
            tmp = path.with_suffix(".tmp")
            tmp.write_text(stored.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(path)  # atomic, so a crash never leaves half a case file
            case.revision, case.updated_at = stored.revision, stored.updated_at

    def get(self, case_id: str) -> CreditFile | None:
        path = self._root / f"{check_key(case_id)}.json"
        if not path.exists():
            return None
        return CreditFile.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, limit: int = 50) -> list[CreditFile]:
        """Most recently updated first.

        Every file is parsed once for its timestamps, keeping only (time, path); full
        validation is spent on the `limit` cases returned.
        """
        stamped = []
        for path in self._root.glob("*.json"):
            raw = json.loads(path.read_text("utf-8"))
            stamped.append(
                (datetime.fromisoformat(raw.get("updated_at") or raw["created_at"]), path)
            )
        stamped.sort(reverse=True)
        return [
            CreditFile.model_validate_json(path.read_text("utf-8")) for _, path in stamped[:limit]
        ]


class GcsBlobStore:
    def __init__(self, bucket: str) -> None:
        import google.cloud.storage as storage

        self._bucket = storage.Client().bucket(bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._bucket.blob(check_key(key)).upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> bytes:
        return bytes(self._bucket.blob(check_key(key)).download_as_bytes())


class FirestoreCaseRepository:
    def __init__(self, project: str | None, collection: str = "cases") -> None:
        import google.cloud.firestore as firestore

        self._firestore = firestore
        self._client = firestore.Client(project=project)
        self._collection = self._client.collection(collection)

    def save(self, case: CreditFile) -> None:
        ref = self._collection.document(check_key(case.case_id))
        expected = case.revision

        updated = utc_now()
        stored = case.model_copy(update={"revision": expected + 1, "updated_at": updated})

        @self._firestore.transactional
        def write(transaction: Any) -> None:
            snapshot = ref.get(transaction=transaction)
            if snapshot.exists and snapshot.get("revision") != expected:
                raise ConcurrentUpdateError(case.case_id)
            # A native timestamp for ordering: the JSON string form does not sort
            # correctly when fractional seconds are omitted.
            transaction.set(ref, stored.model_dump(mode="json") | {_ORDER_FIELD: updated})

        write(self._client.transaction())
        # Only a committed save changes the caller's case.
        case.revision, case.updated_at = stored.revision, updated

    def get(self, case_id: str) -> CreditFile | None:
        snapshot = self._collection.document(check_key(case_id)).get()
        return _from_document(snapshot.to_dict()) if snapshot.exists else None

    def list(self, limit: int = 50) -> list[CreditFile]:
        """Most recently updated first.

        Every document carries the order field: no Firestore deployment predates it (the
        cloud phase starts with this release). A future change of order field needs a
        backfill, because Firestore omits documents lacking the field from the query.
        """
        query = self._collection.order_by(_ORDER_FIELD, direction="DESCENDING").limit(limit)
        return [_from_document(doc.to_dict()) for doc in query.stream()]


_ORDER_FIELD = "_updated"  # storage-only; not part of the CreditFile contract


def _from_document(data: dict[str, Any] | None) -> CreditFile:
    fields = dict(data or {})
    fields.pop(_ORDER_FIELD, None)
    return CreditFile.model_validate(fields)


def build_blob_store(settings: Settings, bucket: str | None, local_dir: str) -> BlobStore:
    """Cloud Storage when deployed; a cloud deployment without a bucket is a config error,
    because container disks are ephemeral and files there would silently vanish."""
    if settings.storage_backend is Backend.GCP:
        if not bucket:
            raise ValueError(f"a bucket is required for '{local_dir}' when storage is gcp")
        return GcsBlobStore(bucket)
    return LocalBlobStore(settings.data_dir / local_dir)


def build_case_repository(settings: Settings) -> CaseRepository:
    if settings.storage_backend is Backend.GCP:
        return FirestoreCaseRepository(settings.gcp_project)
    return LocalCaseRepository(settings.data_dir / "cases")
