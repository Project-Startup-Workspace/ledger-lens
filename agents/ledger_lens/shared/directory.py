"""Organisations, their members and access grants: a JSON file per kind in development,
Firestore collections when deployed. Callers depend only on the protocol."""

import fcntl
import json
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from ledger_lens.shared.config import Backend, Settings
from ledger_lens.shared.schemas import (
    AccessGrant,
    Member,
    Organisation,
    OrgType,
    PlatformConfig,
)

T = TypeVar("T", bound=BaseModel)


class Directory(Protocol):
    def save_org(self, org: Organisation) -> None: ...

    def get_org(self, org_id: str) -> Organisation | None: ...

    def list_orgs(self, org_type: OrgType | None = None) -> list[Organisation]: ...

    def save_member(self, member: Member) -> None: ...

    def get_member(self, uid: str) -> Member | None: ...

    def list_members(self, org_id: str) -> list[Member]: ...

    def save_grant(self, grant: AccessGrant) -> None: ...

    def get_grant(self, grant_id: str) -> AccessGrant | None: ...

    def list_grants(
        self, *, grantor_org_id: str | None = None, grantee_org_id: str | None = None
    ) -> list[AccessGrant]:
        """Grants from or to an organisation, revoked ones included."""
        ...

    def get_config(self) -> PlatformConfig | None: ...

    def save_config(self, config: PlatformConfig) -> None: ...


class LocalDirectory:
    """Three small JSON files, rewritten whole under a lock. Enough for a laptop."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _read(self, name: str, model: type[T]) -> dict[str, T]:
        path = self._root / f"{name}.json"
        raw = json.loads(path.read_text("utf-8")) if path.exists() else {}
        return {key: model.model_validate(value) for key, value in raw.items()}

    def _put(self, name: str, key: str, item: BaseModel) -> None:
        path = self._root / f"{name}.json"
        with (self._root / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            raw = json.loads(path.read_text("utf-8")) if path.exists() else {}
            raw[key] = item.model_dump(mode="json")
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            tmp.replace(path)

    def save_org(self, org: Organisation) -> None:
        self._put("organisations", org.id, org)

    def get_org(self, org_id: str) -> Organisation | None:
        return self._read("organisations", Organisation).get(org_id)

    def list_orgs(self, org_type: OrgType | None = None) -> list[Organisation]:
        orgs = self._read("organisations", Organisation).values()
        return sorted(
            (o for o in orgs if org_type is None or o.type is org_type), key=lambda o: o.name
        )

    def save_member(self, member: Member) -> None:
        self._put("members", member.uid, member)

    def get_member(self, uid: str) -> Member | None:
        return self._read("members", Member).get(uid)

    def list_members(self, org_id: str) -> list[Member]:
        members = self._read("members", Member).values()
        return sorted((m for m in members if m.org_id == org_id), key=lambda m: m.email)

    def save_grant(self, grant: AccessGrant) -> None:
        self._put("grants", grant.id, grant)

    def get_grant(self, grant_id: str) -> AccessGrant | None:
        return self._read("grants", AccessGrant).get(grant_id)

    def list_grants(
        self, *, grantor_org_id: str | None = None, grantee_org_id: str | None = None
    ) -> list[AccessGrant]:
        return sorted(
            (
                g
                for g in self._read("grants", AccessGrant).values()
                if grantor_org_id in (None, g.grantor_org_id)
                and grantee_org_id in (None, g.grantee_org_id)
            ),
            key=lambda g: g.granted_at,
        )

    def get_config(self) -> PlatformConfig | None:
        return self._read("config", PlatformConfig).get("platform")

    def save_config(self, config: PlatformConfig) -> None:
        self._put("config", "platform", config)


class FirestoreDirectory:
    """`organisations`, `members` (keyed by uid) and `grants` collections."""

    def __init__(self, project: str | None) -> None:
        import google.cloud.firestore as firestore

        self._db = firestore.Client(project=project)

    def _set(self, collection: str, key: str, item: BaseModel) -> None:
        self._db.collection(collection).document(key).set(item.model_dump(mode="json"))

    def _get(self, collection: str, key: str, model: type[T]) -> T | None:
        snapshot = self._db.collection(collection).document(key).get()
        return model.model_validate(snapshot.to_dict()) if snapshot.exists else None

    def _where(self, collection: str, model: type[T], **equals: Any) -> list[T]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query: Any = self._db.collection(collection)
        for field, value in equals.items():
            if value is not None:
                query = query.where(filter=FieldFilter(field, "==", value))
        return [model.model_validate(doc.to_dict()) for doc in query.stream()]

    def save_org(self, org: Organisation) -> None:
        self._set("organisations", org.id, org)

    def get_org(self, org_id: str) -> Organisation | None:
        return self._get("organisations", org_id, Organisation)

    def list_orgs(self, org_type: OrgType | None = None) -> list[Organisation]:
        orgs = self._where("organisations", Organisation, type=org_type and org_type.value)
        return sorted(orgs, key=lambda o: o.name)

    def save_member(self, member: Member) -> None:
        self._set("members", member.uid, member)

    def get_member(self, uid: str) -> Member | None:
        return self._get("members", uid, Member)

    def list_members(self, org_id: str) -> list[Member]:
        return sorted(self._where("members", Member, org_id=org_id), key=lambda m: m.email)

    def save_grant(self, grant: AccessGrant) -> None:
        self._set("grants", grant.id, grant)

    def get_grant(self, grant_id: str) -> AccessGrant | None:
        return self._get("grants", grant_id, AccessGrant)

    def list_grants(
        self, *, grantor_org_id: str | None = None, grantee_org_id: str | None = None
    ) -> list[AccessGrant]:
        grants = self._where(
            "grants", AccessGrant, grantor_org_id=grantor_org_id, grantee_org_id=grantee_org_id
        )
        return sorted(grants, key=lambda g: g.granted_at)

    def get_config(self) -> PlatformConfig | None:
        return self._get("config", "platform", PlatformConfig)

    def save_config(self, config: PlatformConfig) -> None:
        self._set("config", "platform", config)


def build_directory(settings: Settings) -> Directory:
    if settings.storage_backend is Backend.GCP:
        return FirestoreDirectory(settings.gcp_project)
    return LocalDirectory(settings.data_dir / "directory")
