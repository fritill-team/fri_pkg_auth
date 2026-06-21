"""In-memory fake repositories for application-layer unit tests.

Each fake implements its corresponding Protocol with a dict-backed
store. No I/O, no async overhead beyond ``async def``. The same fakes
are reused across many test files via direct construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Sequence
from uuid import UUID, uuid4

from pkg_auth.authorization import (
    AuthContext,
    CatalogEntry,
    LocalizedText,
    Membership,
    OrganizationService,
    OrgId,
    Organization,
    Permission,
    PermissionId,
    PermissionKey,
    PermissionScope,
    PermissionVisibility,
    Role,
    RoleId,
    RoleName,
    Service,
    ServiceName,
    ServiceSpec,
    User,
    UserId,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# UserRepository
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FakeUserRepository:
    _by_id: dict[UUID, User] = field(default_factory=dict)
    _by_sub: dict[str, User] = field(default_factory=dict)

    async def get_by_id(self, user_id: UserId) -> User | None:
        return self._by_id.get(user_id.value)

    async def get_by_keycloak_sub(self, sub: str) -> User | None:
        return self._by_sub.get(sub)

    async def upsert_from_identity(
        self,
        *,
        sub: str,
        email: str,
        full_name: str | None,
    ) -> User:
        existing = self._by_sub.get(sub)
        now = _utcnow()
        if existing is not None:
            updated = User(
                id=existing.id,
                keycloak_sub=existing.keycloak_sub,
                email=email,
                full_name=full_name,
                first_seen_at=existing.first_seen_at,
                last_seen_at=now,
            )
            self._by_id[existing.id.value] = updated
            self._by_sub[sub] = updated
            return updated
        user = User(
            id=UserId(uuid4()),
            keycloak_sub=sub,
            email=email,
            full_name=full_name,
            first_seen_at=now,
            last_seen_at=now,
        )
        self._by_id[user.id.value] = user
        self._by_sub[sub] = user
        return user


# --------------------------------------------------------------------------- #
# OrganizationRepository
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FakeOrganizationRepository:
    _by_id: dict[UUID, Organization] = field(default_factory=dict)
    _by_slug: dict[str, UUID] = field(default_factory=dict)
    _user_to_orgs: dict[UUID, set[UUID]] = field(default_factory=dict)

    async def get(self, org_id: OrgId) -> Organization | None:
        return self._by_id.get(org_id.value)

    async def get_by_slug(self, slug: str) -> Organization | None:
        oid = self._by_slug.get(slug)
        return self._by_id.get(oid) if oid is not None else None

    async def create(self, *, slug: str, name: str) -> Organization:
        if slug in self._by_slug:
            raise ValueError(f"slug already exists: {slug!r}")
        org = Organization(
            id=OrgId(uuid4()),
            slug=slug,
            name=name,
            created_at=_utcnow(),
        )
        self._by_id[org.id.value] = org
        self._by_slug[slug] = org.id.value
        return org

    async def update(
        self, org_id: OrgId, *, name: str | None
    ) -> Organization:
        existing = self._by_id.get(org_id.value)
        if existing is None:
            raise ValueError(f"org {org_id} not found")
        updated = Organization(
            id=existing.id,
            slug=existing.slug,
            name=name if name is not None else existing.name,
            created_at=existing.created_at,
        )
        self._by_id[existing.id.value] = updated
        return updated

    async def delete(self, org_id: OrgId) -> None:
        existing = self._by_id.pop(org_id.value, None)
        if existing is not None:
            self._by_slug.pop(existing.slug, None)
            for orgs in self._user_to_orgs.values():
                orgs.discard(org_id.value)

    async def list_for_user(self, user_id: UserId) -> list[Organization]:
        org_ids = self._user_to_orgs.get(user_id.value, set())
        return [
            self._by_id[oid] for oid in org_ids if oid in self._by_id
        ]

    # ----- test helper (not part of Protocol) -------------------------- #
    def _link(self, user_id: UserId, org_id: OrgId) -> None:
        self._user_to_orgs.setdefault(user_id.value, set()).add(org_id.value)


# --------------------------------------------------------------------------- #
# RoleRepository
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FakeRoleRepository:
    _by_id: dict[UUID, Role] = field(default_factory=dict)
    _by_org_name: dict[tuple[UUID | None, str], UUID] = field(default_factory=dict)

    async def get(self, role_id: RoleId) -> Role | None:
        return self._by_id.get(role_id.value)

    async def get_by_name(
        self, org_id: OrgId | None, name: RoleName
    ) -> Role | None:
        key = (org_id.value if org_id is not None else None, str(name))
        rid = self._by_org_name.get(key)
        return self._by_id.get(rid) if rid is not None else None

    async def create(
        self,
        *,
        org_id: OrgId | None,
        name: RoleName,
        description: str | None,
        permission_keys: Sequence[PermissionKey],
    ) -> Role:
        key = (org_id.value if org_id is not None else None, str(name))
        if key in self._by_org_name:
            raise ValueError(f"role already exists: {key}")
        role = Role(
            id=RoleId(uuid4()),
            organization_id=org_id,
            name=name,
            description=description,
            permission_keys=frozenset(str(k) for k in permission_keys),
        )
        self._by_id[role.id.value] = role
        self._by_org_name[key] = role.id.value
        return role

    async def update(
        self,
        role_id: RoleId,
        *,
        name: RoleName | None,
        description: str | None,
        permission_keys: Sequence[PermissionKey] | None,
    ) -> Role:
        existing = self._by_id.get(role_id.value)
        if existing is None:
            raise ValueError(f"role {role_id} not found")
        new_name = name if name is not None else existing.name
        new_perms = (
            frozenset(str(k) for k in permission_keys)
            if permission_keys is not None
            else existing.permission_keys
        )
        updated = Role(
            id=existing.id,
            organization_id=existing.organization_id,
            name=new_name,
            description=description if description is not None else existing.description,
            permission_keys=new_perms,
        )
        self._by_id[existing.id.value] = updated
        if name is not None and str(name) != str(existing.name):
            old_org_value = (
                existing.organization_id.value
                if existing.organization_id is not None
                else None
            )
            self._by_org_name.pop((old_org_value, str(existing.name)), None)
            self._by_org_name[(old_org_value, str(new_name))] = existing.id.value
        return updated

    async def delete(self, role_id: RoleId) -> None:
        existing = self._by_id.pop(role_id.value, None)
        if existing is not None:
            org_value = (
                existing.organization_id.value
                if existing.organization_id is not None
                else None
            )
            self._by_org_name.pop((org_value, str(existing.name)), None)


# --------------------------------------------------------------------------- #
# MembershipRepository
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FakeMembershipRepository:
    """Fake membership repo. Wire ``role_repo`` so it can build AuthContexts.

    Models the v1.3 multi-role-per-org schema: a user can hold multiple
    memberships in the same organization (one row per role). Storage is
    keyed by ``(user_id, org_id, role_id)``, and ``load_auth_context``
    aggregates the union of all active memberships for ``(user, org)``.
    """

    role_repo: "FakeRoleRepository | None" = None
    _by_key: dict[tuple[UUID, UUID, UUID], Membership] = field(default_factory=dict)

    async def get(
        self, user_id: UserId, org_id: OrgId
    ) -> Membership | None:
        for (uid, oid, _), m in self._by_key.items():
            if uid == user_id.value and oid == org_id.value:
                return m
        return None

    async def upsert(
        self,
        *,
        user_id: UserId,
        org_id: OrgId,
        role_id: RoleId,
        status: str,
    ) -> Membership:
        if self.role_repo is None:
            raise RuntimeError(
                "FakeMembershipRepository.role_repo must be wired for upsert"
            )
        role = await self.role_repo.get(role_id)
        if role is None:
            raise ValueError(f"role {role_id} not found")
        key = (user_id.value, org_id.value, role_id.value)
        existing = self._by_key.get(key)
        if existing is not None:
            updated = Membership(
                id=existing.id,
                user_id=user_id,
                organization_id=org_id,
                role_id=role_id,
                role_name=role.name,
                status=status,
                joined_at=existing.joined_at,
            )
        else:
            updated = Membership(
                id=uuid4(),
                user_id=user_id,
                organization_id=org_id,
                role_id=role_id,
                role_name=role.name,
                status=status,
                joined_at=_utcnow(),
            )
        self._by_key[key] = updated
        return updated

    async def delete(self, user_id: UserId, org_id: OrgId) -> None:
        # Remove ALL memberships for (user, org) — multi-role aware.
        stale = [
            k for k in self._by_key
            if k[0] == user_id.value and k[1] == org_id.value
        ]
        for k in stale:
            self._by_key.pop(k, None)

    async def load_auth_context(
        self, user_id: UserId, org_id: OrgId
    ) -> AuthContext | None:
        if self.role_repo is None:
            return None
        role_names: set[str] = set()
        perms: set[str] = set()
        active_count = 0
        for (uid, oid, _), m in self._by_key.items():
            if uid != user_id.value or oid != org_id.value:
                continue
            if m.status != "active":
                continue
            role = await self.role_repo.get(m.role_id)
            if role is None:
                continue
            active_count += 1
            role_names.add(str(role.name))
            perms.update(role.permission_keys)
        if active_count == 0:
            return None
        return AuthContext(
            user_id=user_id,
            organization_id=org_id,
            role_names=frozenset(role_names),
            perms=frozenset(perms),
        )

    async def list_for_user(self, user_id: UserId) -> list[Membership]:
        return [
            m for k, m in self._by_key.items() if k[0] == user_id.value
        ]


# --------------------------------------------------------------------------- #
# PermissionCatalogRepository
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FakePermissionCatalogRepository:
    _by_id: dict[UUID, Permission] = field(default_factory=dict)
    _by_key: dict[str, UUID] = field(default_factory=dict)

    async def register_many(
        self,
        *,
        service_name: str,
        entries: Sequence[CatalogEntry],
    ) -> None:
        for entry in entries:
            existing_id = self._by_key.get(str(entry.key))
            if existing_id is not None:
                old = self._by_id[existing_id]
                self._by_id[existing_id] = Permission(
                    id=old.id,
                    key=entry.key,
                    service_name=service_name,
                    description=entry.description,
                    visibility=entry.visibility,
                )
            else:
                perm = Permission(
                    id=PermissionId(uuid4()),
                    key=entry.key,
                    service_name=service_name,
                    description=entry.description,
                    visibility=entry.visibility,
                )
                self._by_id[perm.id.value] = perm
                self._by_key[str(entry.key)] = perm.id.value

    def _filter_scope(
        self, perms: list[Permission], scope: PermissionScope
    ) -> list[Permission]:
        if scope in ("org", "tenant"):
            return [
                p for p in perms
                if p.visibility != PermissionVisibility.PLATFORM_ONLY
            ]
        if scope == "platform":
            return [
                p for p in perms
                if p.visibility != PermissionVisibility.TENANT_ONLY
            ]
        return perms

    async def list_all(
        self, *, scope: PermissionScope = "all"
    ) -> list[Permission]:
        return self._filter_scope(list(self._by_id.values()), scope)

    async def list_for_service(
        self, service_name: str, *, scope: PermissionScope = "all"
    ) -> list[Permission]:
        return self._filter_scope(
            [p for p in self._by_id.values() if p.service_name == service_name],
            scope,
        )

    async def get_service_map(self) -> dict[str, str]:
        return {
            str(p.key): p.service_name for p in self._by_id.values()
        }

    async def prune_absent(
        self,
        *,
        service_name: str,
        keep_keys: Iterable[PermissionKey],
    ) -> int:
        keys = {str(k) for k in keep_keys}
        victims = [
            p for p in self._by_id.values()
            if p.service_name == service_name and str(p.key) not in keys
        ]
        for p in victims:
            self._by_id.pop(p.id.value, None)
            self._by_key.pop(str(p.key), None)
        return len(victims)


# --------------------------------------------------------------------------- #
# ServiceRepository
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FakeServiceRepository:
    _by_name: dict[str, Service] = field(default_factory=dict)

    async def upsert_many(self, services: Sequence[ServiceSpec]) -> None:
        # Vendor flag overlay: set flags; preserve a service-owned label on
        # conflict, seed it only on insert.
        for s in services:
            existing = self._by_name.get(str(s.name))
            self._by_name[str(s.name)] = Service(
                name=s.name,
                display_label=(
                    existing.display_label if existing is not None
                    else s.display_label
                ),
                auto_provision=s.auto_provision,
                saas_available=s.saas_available,
                created_at=existing.created_at if existing else _utcnow(),
            )

    async def register_identity(
        self, *, name: str, display_label: LocalizedText | None = None
    ) -> None:
        label = display_label if display_label is not None else LocalizedText({})
        existing = self._by_name.get(name)
        if existing is None:
            self._by_name[name] = Service(
                name=ServiceName(name),
                display_label=label,
                auto_provision=False,
                saas_available=False,
                created_at=_utcnow(),
            )
        elif label.as_dict():
            # Identity is service-owned: update the label, keep vendor flags.
            self._by_name[name] = Service(
                name=existing.name,
                display_label=label,
                auto_provision=existing.auto_provision,
                saas_available=existing.saas_available,
                created_at=existing.created_at,
            )

    async def get(self, name: ServiceName) -> Service | None:
        return self._by_name.get(str(name))

    async def list_all(self) -> list[Service]:
        return [self._by_name[n] for n in sorted(self._by_name)]

    async def prune_absent(self, *, keep: Iterable[ServiceName]) -> int:
        keep_names = {str(n) for n in keep}
        victims = [n for n in self._by_name if n not in keep_names]
        for n in victims:
            self._by_name.pop(n, None)
        return len(victims)


# --------------------------------------------------------------------------- #
# OrganizationServiceRepository
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FakeOrganizationServiceRepository:
    _by_key: dict[tuple[UUID, str], OrganizationService] = field(
        default_factory=dict
    )

    async def list_enabled_service_names(self, org_id: OrgId) -> set[str]:
        return {
            svc
            for (oid, svc), e in self._by_key.items()
            if oid == org_id.value and e.enabled
        }

    async def get(
        self, org_id: OrgId, service_name: ServiceName
    ) -> OrganizationService | None:
        return self._by_key.get((org_id.value, str(service_name)))

    async def enable(
        self, org_id: OrgId, service_name: ServiceName, *, source: str
    ) -> OrganizationService:
        ent = OrganizationService(
            organization_id=org_id,
            service_name=service_name,
            enabled=True,
            source=source,
            granted_at=_utcnow(),
        )
        self._by_key[(org_id.value, str(service_name))] = ent
        return ent

    async def disable(
        self, org_id: OrgId, service_name: ServiceName
    ) -> None:
        self._by_key.pop((org_id.value, str(service_name)), None)

    async def bulk_enable(
        self,
        org_id: OrgId,
        service_names: Sequence[ServiceName],
        *,
        source: str,
    ) -> None:
        for name in service_names:
            await self.enable(org_id, name, source=source)
