"""Where evidence files and case files live: local folders in development, Google Cloud
(Cloud Storage and Firestore) when deployed. Callers depend only on the protocols."""

import fcntl
import re
from pathlib import Path
from typing import Protocol

from ledger_lens.shared.config import Backend, Settings
from ledger_lens.shared.schemas import CreditFile

_SAFE_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


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

    def list(self, limit: int = 50) -> list[CreditFile]: ...


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
            case.revision += 1
            tmp = path.with_suffix(".tmp")
            tmp.write_text(case.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(path)  # atomic, so a crash never leaves half a case file

    def get(self, case_id: str) -> CreditFile | None:
        path = self._root / f"{check_key(case_id)}.json"
        if not path.exists():
            return None
        return CreditFile.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, limit: int = 50) -> list[CreditFile]:
        cases = [
            CreditFile.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self._root.glob("*.json")
        ]
        return sorted(cases, key=lambda c: c.created_at, reverse=True)[:limit]


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

        self._collection = firestore.Client(project=project).collection(collection)

    def save(self, case: CreditFile) -> None:
        self._collection.document(case.case_id).set(case.model_dump(mode="json"))

    def get(self, case_id: str) -> CreditFile | None:
        snapshot = self._collection.document(check_key(case_id)).get()
        return CreditFile.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def list(self, limit: int = 50) -> list[CreditFile]:
        query = self._collection.order_by("created_at", direction="DESCENDING").limit(limit)
        return [CreditFile.model_validate(doc.to_dict()) for doc in query.stream()]


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
