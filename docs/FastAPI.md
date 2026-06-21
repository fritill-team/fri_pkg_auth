# FastAPI Integration

## Setup (Mode B — consumer, the common case)

Most services share the ACL database with a source-of-truth peer
(e.g. `itq_users`) and do **not** own the `users` table. Those services
must read through, never write: use `ResolveUserFromJwtUseCase`.

```python
from pkg_auth.authorization.application.use_cases.resolve_user_from_jwt import (
    ResolveUserFromJwtUseCase,
)
from pkg_auth.authorization.application.use_cases.resolve_auth_context import (
    ResolveAuthContextUseCase,
)
from pkg_auth.integrations.fastapi import (
    create_authentication,
    make_get_auth_context,
    require_permission,
    install_exception_handlers,
)

# 1. Identity (Keycloak JWT)
auth = create_authentication(
    keycloak_base_url="https://auth.example.com",
    realm="itqadem",
    audience="courses-service",
)

# 2. Authorization context (composes identity + ACL lookup)
resolve_user = ResolveUserFromJwtUseCase(user_repo=user_repo)
resolve = ResolveAuthContextUseCase(membership_repo=membership_repo)
get_auth_context = make_get_auth_context(
    get_identity=auth.get_identity,
    resolve_user_use_case=resolve_user,       # Mode B — reader
    resolve_use_case=resolve,
    organization_repo=org_repo,
    header_name="X-Organization-Id",          # default
)

# 3. Exception handlers (optional — makes domain errors map to HTTP)
install_exception_handlers(app)
```

To enable the optional **service guard** (default-deny: resolved perms are
filtered to the services the org has enabled), construct `resolve` with the
extra repos — the platform org bypasses the guard:

```python
from pkg_auth.authorization.application.use_cases.resolve_auth_context import (
    ResolveAuthContextUseCase,
)

resolve = ResolveAuthContextUseCase(
    membership_repo=membership_repo,
    org_service_repo=org_service_repo,   # e.g. SqlAlchemyOrganizationServiceRepository
    catalog_repo=catalog_repo,
    platform_org_id=platform_org_id,
)
```

Keep the org's enabled-service set in sync with the catalog via the
`pkg-auth-sync-services` CLI, and wrap `org_service_repo` in
`CachedOrganizationServiceRepository` to cache the enabled-service set on the
guard hot path.

A Mode B request whose Keycloak `sub` hasn't been mirrored into the
local ACL yet raises `UserNotProvisioned` → **HTTP 403**. That's the
signal the source-of-truth service hasn't provisioned the user yet;
the consumer never writes in response.

## Setup (Mode A — source-of-truth service)

Only the service that owns the `users` schema (e.g. `itq_users`)
should upsert on JWT sight. Those services pass `sync_user_use_case`
instead — the two params are mutually exclusive.

```python
from pkg_auth.authorization.application.use_cases.sync_user_from_jwt import (
    SyncUserFromJwtUseCase,
)

sync_user = SyncUserFromJwtUseCase(user_repo=user_repo)
get_auth_context = make_get_auth_context(
    get_identity=auth.get_identity,
    sync_user_use_case=sync_user,             # Mode A — writer
    resolve_use_case=resolve,
    organization_repo=org_repo,
)
```

Passing both (or neither) raises `ValueError` at factory-call time.

## Protecting routes

### Via `require_permission`

```python
@router.get("/courses/{id}")
async def get_course(
    id: str,
    bundle: tuple[IdentityContext, AuthContext] = Depends(
        require_permission("course:view", get_auth_context=get_auth_context)
    ),
):
    identity, auth_ctx = bundle
    ...
```

### Via route-level dependencies

```python
@router.delete(
    "/courses/{id}",
    dependencies=[Depends(require_permission("course:delete", get_auth_context=get_auth_context))],
)
async def delete_course(id: str):
    ...
```

## Error mapping

| Condition | Status |
|---|---|
| No/invalid token | 401 |
| Missing `X-Organization-Id` | 400 |
| User not provisioned (Mode B) | 403 |
| User not a member | 403 |
| Permission missing | 403 |
| Unknown org | 404 |

## Reference example

See [`examples/itqadem_courses_app`](../examples/itqadem_courses_app) for the full wiring.
