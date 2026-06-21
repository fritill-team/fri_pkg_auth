# User Guide

This guide covers the core concepts of `pkg-auth` and how to protect routes.
For framework wiring details see [FastAPI](FastAPI), [Django](Django), and
[Strawberry](Strawberry).

## IdentityContext vs AuthContext

`pkg-auth` splits *who you are* from *what you can do*:

- **`IdentityContext`** comes from `pkg_auth.authentication`. It is the result of
  validating a Keycloak JWT — identity claims only, no database access.
- **`AuthContext`** comes from `pkg_auth.authorization`. It is the resolved,
  per-request authorization state for a `(user, organization)` pair:

  ```python
  auth_ctx.user_id
  auth_ctx.organization_id
  auth_ctx.role_names   # frozenset[str] — a user may hold multiple roles
  auth_ctx.perms        # frozenset[str] — union of all active roles' perms

  auth_ctx.has("course:view")        # -> bool
  auth_ctx.require("course:edit")    # raises MissingPermission
  auth_ctx.has_role("instructor")    # -> bool
  ```

## The permission model

Permissions are `resource:action` keys held in a global catalog. Each entry has:

- a **visibility** — `platform_only`, `shared` (default), or `tenant_only`; and
- a **localized description** (`LocalizedText`, a `{locale: text}` JSONB map).

Build entries with `CatalogEntry.make`, which coerces a plain string into the
configured default locale (`ACL_DEFAULT_LOCALE`, default `en`):

```python
from pkg_auth.authorization.application.use_cases.register_permission_catalog import (
    CatalogEntry,
)
from pkg_auth.authorization.domain.value_objects import PermissionVisibility

entries = [
    CatalogEntry.make("course:view", "View a course"),
    CatalogEntry.make("course:edit", {"en": "Edit a course", "ar": "تعديل دورة"}),
    CatalogEntry.make(
        "organizations:create",
        "Create organizations",
        PermissionVisibility.PLATFORM_ONLY,
    ),
]
```

## Registering a catalog on boot

Each service idempotently registers the permission keys it knows about on
startup. The repository upserts by key, so calling it on every restart is safe.

```python
from pkg_auth.authorization.application.use_cases.register_permission_catalog import (
    RegisterPermissionCatalogUseCase,
)

await RegisterPermissionCatalogUseCase(
    catalog_repo=catalog_repo,
    service_repo=service_repo,  # optional: ensures a services row exists
).execute(service_name="courses", entries=entries)
```

## Mode A vs Mode B

- **Mode A (source of truth)** — your service owns the `users` table, extends the
  bundled mixins, applies the schema, and lazily upserts users from the JWT with
  `SyncUserFromJwtUseCase`.
- **Mode B (consumer)** — your service shares the central ACL read-only and uses
  `ResolveUserFromJwtUseCase`, which 403s if the user is not provisioned.

You pass **exactly one** of `sync_user_use_case` (Mode A) or
`resolve_user_use_case` (Mode B) when wiring the auth-context dependency.

## Protecting routes (FastAPI)

```python
from fastapi import Depends, FastAPI
from pkg_auth.authentication import IdentityContext
from pkg_auth.authorization import AuthContext
from pkg_auth.integrations.fastapi import require_permission

app = FastAPI()

@app.get("/courses/{id}")
async def get_course(
    id: str,
    bundle: tuple[IdentityContext, AuthContext] = Depends(
        require_permission("course:view", get_auth_context=get_auth_context)
    ),
):
    identity, auth_ctx = bundle
    return {"course_id": id, "roles": sorted(auth_ctx.role_names)}
```

See [FastAPI](FastAPI) for building `get_auth_context`, and [Django](Django) /
[Strawberry](Strawberry) for the equivalents.

## Platform-admin checks

`AuthContext` deliberately carries no `is_platform` flag. Platform-admin
detection is a service-level policy: cache your platform org's id at startup and
compare with the helper:

```python
from pkg_auth.authorization import is_platform_context

if is_platform_context(auth_ctx, platform_org_id):
    ...  # platform-admin path
```

## Services and the service guard

Organizations are entitled to **services**, and the default-deny **service guard**
drops any resolved permission whose owning service the org has not enabled (the
platform org bypasses the guard). This is configured when building the auth
context, not at the route level. See
[Authorization](Authorization) for the model and
[Upgrade-Service-Guard](Upgrade-Service-Guard) for wiring.
