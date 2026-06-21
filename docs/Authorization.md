# Authorization Model

`pkg_auth.authorization` provides per-(user, organization) RBAC backed by a Postgres database the package owns.

## Database topology

All itqadem services connect to a **single shared central ACL database**, owned and migrated by the users service. Authorization checks hit this database on every protected request (with an optional in-process or Redis cache in front). There are no events, no broker, and no per-service cache replicas.

## Schema (`acl.*`)

The schema lives in a Postgres schema called `acl` and contains:

| Table | Purpose |
|---|---|
| `users` | Lazily upserted from JWT on first sight. FK anchor for memberships. |
| `organizations` | Top-level grouping. Identified by `slug` (string) or `id` (bigint). |
| `permissions` | Global permission catalog. Populated by services on boot. Each row has a `visibility` (`platform_only`/`shared`/`tenant_only`) and a localized JSONB `description`. |
| `roles` | Per-org (or global template). Links to permissions via `role_permissions`. |
| `role_permissions` | Many-to-many join between roles and permissions. |
| `memberships` | One row per (user, org, role). Links a user to a role in an org. `UNIQUE(user_id, organization_id, role_id)` — a user may hold **multiple roles** per (user, org); the resolved `AuthContext.perms` is the **union** of all active roles' permissions. |
| `membership_invitations` | Pending invitations for non-member users. |
| `auth_audit_log` | Append-only log of ACL mutations. |
| `services` | Service registry. Vendor-controlled `auto_provision` / `saas_available` flags, set via `pkg-auth-sync-services`. |
| `organization_services` | Per-org service entitlements driving the default-deny service guard. |

### Permission visibility & the service guard

`permissions.visibility` controls which role builders may use a permission:
`platform_only` (platform org only), `shared` (everywhere, default), and
`tenant_only` (normal orgs only — **hidden from the platform org**). The catalog
repo's `scope=` filter maps to this: `"platform"` → platform_only ∪ shared,
`"tenant"`/`"org"` → shared ∪ tenant_only.

The **service guard** (`ResolveAuthContextUseCase` with `org_service_repo` +
`catalog_repo` + `platform_org_id`) filters a user's resolved permissions down
to the services their org has enabled in `organization_services`
(**default-deny** — a perm whose owning service is not enabled is dropped). The
platform org bypasses the guard. New orgs get `auto_provision` services via
`ProvisionDefaultServicesUseCase`; platform admins toggle `saas_available`
services via `SetOrganizationServiceUseCase`. See
[Upgrade-Service-Guard](Upgrade-Service-Guard.md) for wiring.

### Applying migrations

The schema is owned by Alembic migrations shipped inside the package:

```python
from pkg_auth.authorization.adapters.sqlalchemy import MIGRATIONS_DIR
```

In your users service's `alembic/env.py`:

```python
config.set_main_option(
    "version_locations",
    f"{config.get_main_option('version_locations')} {MIGRATIONS_DIR}",
)
```

Then: `alembic upgrade pkg_auth_acl@head`

The bundled revision chain runs `pkg_auth_acl_0001` (initial) through `0005`,
including `0003` (permission visibility), `0004` (localized JSONB `description`),
and `0005` (`services` + `organization_services` tables).

Other services don't run migrations — they connect to the same database the users service migrated.

## Core concepts

### AuthContext

The hot-path authorization primitive. Built once per request by `ResolveAuthContextUseCase` and injected into handlers:

```python
@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: UserId
    organization_id: OrgId
    role_names: frozenset[str]
    perms: frozenset[str]

    def has(self, perm: str) -> bool: ...
    def require(self, perm: str) -> None: ...  # raises MissingPermission
    def has_role(self, role: str) -> bool: ...
```

### Permission keys

Permission keys use the `resource:action` format (e.g. `"course:edit"`, `"billing:invoice:refund"`). Each service declares its own keys in code and registers them on boot via `RegisterPermissionCatalogUseCase`. The catalog serves the users service's admin UI for building roles.

### Syncing permission catalogs (deploy-time)

Runtime services should only have SELECT access to the ACL database and
register their catalog via `RegisterPermissionCatalogUseCase` (idempotent
UPSERT, no deletes). When a service *removes* a permission from its code
catalog, the row becomes an orphan — nothing breaks, but it lingers.

To prune removed permissions, run `pkg-auth-sync-catalog` from a deploy-time
init container holding a *separate* credential with INSERT/UPDATE/DELETE on
the `permissions` table only.

**Two Vault database roles per consumer service:**

- **Runtime role** — `SELECT` on all ACL tables. Used by the long-running
  process. No writes, ever.
- **Sync role** — `SELECT` on ACL tables + `INSERT, UPDATE, DELETE` on
  `permissions` only. Used exclusively by the init container. Can have a
  short lease TTL (minutes).

**CLI usage:**

```bash
pkg-auth-sync-catalog \
    --service courses \
    --catalog courses.domain.permissions:CATALOG \
    --db-url "$ACL_DATABASE_URL"
```

`--dry-run` prints the diff (`to add`, `to prune`) without writing — useful
the first time you run sync against an existing database.

The CLI is factored so services can compose their own entrypoint if they
need extra flags or a custom catalog loader:

```python
from pkg_auth.authorization.cli.sync_catalog import (
    build_arg_parser, load_catalog, run,
)
```

> **Warning — FK CASCADE.** The `role_permissions.permission_id` FK is
> `ON DELETE CASCADE`. When sync deletes a permission row, any
> `role_permissions` row referencing it is silently dropped, meaning roles
> that granted the pruned permission lose it with no error and no log at
> the DB level. Removing a permission from a service's catalog is an
> intentional breaking change to every role that granted it. Always run
> `--dry-run` first on shared environments.

### Extending the schema

The users service can extend `users`, `organizations`, and `memberships` with extra fields. Two patterns are supported:

1. **Extension tables** (recommended): create service-owned tables with `REFERENCES acl.users(id)`. Zero coupling to pkg_auth releases.
2. **Direct ALTER** (escape hatch): add columns to `acl.users` with a `usrsvc_` prefix to avoid future collisions.

See the plan file for full details on both patterns.
