"""Authorization domain ports (Protocol-based repositories).

These Protocols are the contract between the application layer and the
adapter layer. Adapters live under ``pkg_auth.authorization.adapters``
(SQLAlchemy, Django ORM, cache decorator). The application layer imports
only from this module; it must not import any concrete adapter.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Literal, Protocol, Sequence

from .entities import (
    AuthContext,
    Membership,
    Organization,
    OrganizationService,
    Permission,
    Role,
    Service,
    User,
)
from .value_objects import (
    LocalizedText,
    OrgId,
    PermissionKey,
    RoleId,
    RoleName,
    ServiceName,
    UserId,
)

if TYPE_CHECKING:
    from ..application.use_cases.register_permission_catalog import (
        CatalogEntry,
    )
    from ..application.use_cases.sync_service_catalog import ServiceSpec

# Role-builder visibility filter:
#   - "platform"      → platform_only ∪ shared (what a platform-org role may use)
#   - "tenant"/"org"  → shared ∪ tenant_only  (what a normal-org role may use)
#   - "all"           → no filter
# "org" is kept as a backward-compatible alias for "tenant".
PermissionScope = Literal["org", "tenant", "platform", "all"]


class UserRepository(Protocol):
    """Read/write access to the ``users`` table.

    The package lazily upserts users on first JWT sight via
    :meth:`upsert_from_identity`; explicit creation is not exposed.
    """

    async def get_by_id(self, user_id: UserId) -> User | None: ...
    async def get_by_keycloak_sub(self, sub: str) -> User | None: ...
    async def upsert_from_identity(
        self,
        *,
        sub: str,
        email: str,
        full_name: str | None,
    ) -> User: ...


class OrganizationRepository(Protocol):
    """Read/write access to the ``organizations`` table."""

    async def get(self, org_id: OrgId) -> Organization | None: ...
    async def get_by_slug(self, slug: str) -> Organization | None: ...
    async def create(self, *, slug: str, name: str) -> Organization: ...
    async def update(
        self, org_id: OrgId, *, name: str | None
    ) -> Organization: ...
    async def delete(self, org_id: OrgId) -> None: ...
    async def list_for_user(self, user_id: UserId) -> list[Organization]: ...


class RoleRepository(Protocol):
    """Read/write access to the ``roles`` table (and the ``role_permissions`` join)."""

    async def get(self, role_id: RoleId) -> Role | None: ...
    async def get_by_name(
        self, org_id: OrgId | None, name: RoleName
    ) -> Role | None: ...
    async def create(
        self,
        *,
        org_id: OrgId | None,
        name: RoleName,
        description: str | None,
        permission_keys: Sequence[PermissionKey],
    ) -> Role: ...
    async def update(
        self,
        role_id: RoleId,
        *,
        name: RoleName | None,
        description: str | None,
        permission_keys: Sequence[PermissionKey] | None,
    ) -> Role: ...
    async def delete(self, role_id: RoleId) -> None: ...


class MembershipRepository(Protocol):
    """Read/write access to the ``memberships`` table.

    The hot path is :meth:`load_auth_context`, which the FastAPI / Django /
    Strawberry deps call on every protected request. SQLAlchemy / Django
    implementations should do this in one query (joined with the role and
    its permissions) so the call site never round-trips for individual
    perms.
    """

    async def get(
        self, user_id: UserId, org_id: OrgId
    ) -> Membership | None: ...
    async def upsert(
        self,
        *,
        user_id: UserId,
        org_id: OrgId,
        role_id: RoleId,
        status: str,
    ) -> Membership: ...
    async def delete(self, user_id: UserId, org_id: OrgId) -> None: ...
    async def load_auth_context(
        self, user_id: UserId, org_id: OrgId
    ) -> AuthContext | None: ...
    async def list_for_user(self, user_id: UserId) -> list[Membership]: ...


class PermissionCatalogRepository(Protocol):
    """Read/write access to the ``permissions`` table (the global perm catalog).

    The ``scope`` argument on the list methods filters by each row's
    ``visibility``:

    - ``"platform"``     → platform_only ∪ shared
    - ``"tenant"``/``"org"`` → shared ∪ tenant_only
    - ``"all"``          → no filter (default)
    """

    async def register_many(
        self,
        *,
        service_name: str,
        entries: Sequence["CatalogEntry"],
    ) -> None: ...
    async def list_all(
        self, *, scope: PermissionScope = "all"
    ) -> list[Permission]: ...
    async def list_for_service(
        self, service_name: str, *, scope: PermissionScope = "all"
    ) -> list[Permission]: ...
    async def get_service_map(self) -> dict[str, str]:
        """Return a ``{permission_key: service_name}`` map for the whole
        catalog. Used by the service guard in
        :class:`ResolveAuthContextUseCase` to map a user's perm keys to the
        services that own them. Small and slow-changing → cacheable.
        """
        ...
    async def prune_absent(
        self,
        *,
        service_name: str,
        keep_keys: Iterable[PermissionKey],
    ) -> int:
        """Delete permissions owned by ``service_name`` whose key is NOT in
        ``keep_keys``. Returns the number of rows deleted.

        If ``keep_keys`` is empty, every row for ``service_name`` is deleted.
        The FK ``role_permissions.permission_id`` is ``ON DELETE CASCADE``, so
        role assignments referencing the pruned rows are silently dropped.
        """
        ...


class ServiceRepository(Protocol):
    """Read/write access to the ``services`` table (the service registry).

    Ownership is split into two non-overlapping concerns so services can be
    rolled out independently (the *overlay* model):

    - **Identity** (``name`` + ``display_label``) is owned by each service and
      written via :meth:`register_identity` from its own catalog sync
      (``pkg-auth-sync-catalog``). A service registers itself.
    - **Vendor flags** (``auto_provision``, ``saas_available``) are owned by the
      vendor and written via :meth:`upsert_many` (``pkg-auth-sync-services``).

    Neither path clobbers the other's fields: :meth:`register_identity` never
    touches the flags, and :meth:`upsert_many` never overwrites an existing
    row's ``display_label``. Because each service owns its own row,
    ``pkg-auth-sync-services`` does NOT prune by default; :meth:`prune_absent`
    remains available for an explicit, opt-in cleanup.
    """

    async def upsert_many(self, services: Sequence["ServiceSpec"]) -> None: ...
    async def register_identity(
        self, *, name: str, display_label: LocalizedText | None = None
    ) -> None:
        """Self-register a service's identity (idempotent).

        Insert a row for ``name`` if absent (flags default ``False`` so the
        default-deny guard does not strip the service's perms before the vendor
        configures it). If the row exists, update ``display_label`` only when a
        non-empty label is given; never touch the vendor flags.
        """
        ...
    async def get(self, name: ServiceName) -> Service | None: ...
    async def list_all(self) -> list[Service]: ...
    async def prune_absent(
        self, *, keep: Iterable[ServiceName]
    ) -> int: ...


class OrganizationServiceRepository(Protocol):
    """Read/write access to the ``organization_services`` table (per-org
    service entitlements that drive the service guard).
    """

    async def list_enabled_service_names(self, org_id: OrgId) -> set[str]: ...
    async def get(
        self, org_id: OrgId, service_name: ServiceName
    ) -> OrganizationService | None: ...
    async def enable(
        self, org_id: OrgId, service_name: ServiceName, *, source: str
    ) -> OrganizationService: ...
    async def disable(
        self, org_id: OrgId, service_name: ServiceName
    ) -> None: ...
    async def bulk_enable(
        self,
        org_id: OrgId,
        service_names: Sequence[ServiceName],
        *,
        source: str,
    ) -> None: ...
