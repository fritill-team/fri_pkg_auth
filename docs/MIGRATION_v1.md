# Migrating from pkg_auth v0.x to v1.0

v1.0 is a breaking release. The old claim-based authorization model is removed entirely and replaced by a database-backed ACL. This guide covers every change you need to make.

## Import renames

| v0.x import | v1.0 import |
|---|---|
| `from pkg_auth import AccessContext` | `from pkg_auth.authentication import IdentityContext` |
| `from pkg_auth import AccessRights` | **removed** — authorization is now DB-based |
| `from pkg_auth import AccessRequirement` | **removed** |
| `from pkg_auth import ClaimSet` | **removed** |
| `from pkg_auth import AuthorizeAccessUseCase` | **removed** — use `ResolveAuthContextUseCase` + `AuthContext.require()` |
| `from pkg_auth import AuthenticateTokenUseCase` | `from pkg_auth.authentication import AuthenticateTokenUseCase` |
| `from pkg_auth import JWTTokenDecoder` | `from pkg_auth.authentication.adapters.keycloak import JWTTokenDecoder` |
| `from pkg_auth import TokenExpiredError` | `from pkg_auth.authentication import TokenExpiredError` |
| `from pkg_auth import AuthorizationError` | `from pkg_auth.authorization import AuthorizationError` |
| `from pkg_auth.integrations.fastapi import create_fastapi_auth` | `from pkg_auth.integrations.fastapi import create_authentication` |
| `fastapi_auth.get_current_user` | `auth.get_identity` (returns `IdentityContext`, not `AccessContext`) |
| `fastapi_auth.require_permissions("foo")` | `require_permission("foo", get_auth_context=get_auth_context)` (Depends-wrapper, not a method) |
| `fastapi_auth.require_realm_roles(...)` | **removed** — roles are now an ACL concept, not a Keycloak claim |
| `FastAPIDecorators.require_permissions(...)` | **removed** — use `Depends(require_permission(...))` |
| `create_strawberry_auth(...)` | `make_context_getter(...)` (different parameter shape) |
| `StrawberryAuth.require_permissions(...)` | `RequirePermission("perm")` (Strawberry BasePermission class) |

## Key behavioral changes

1. **Keycloak is authentication only.** The package no longer reads `realm_roles`, `client_roles`, or `permissions` from JWT claims. All authorization comes from the ACL database.

2. **`IdentityContext` replaces `AccessContext`.** It's a flat frozen dataclass with only identity/session fields. No `rights` attribute. The `subject` field is now *required* (previously optional).

3. **`AuthContext` is the new authorization primitive.** It carries `user_id`, `organization_id`, `role_names: frozenset[str]`, and `perms: frozenset[str]`. You get it from `make_get_auth_context()`'s Depends-able, which reads `X-Organization-Id` from the request header.

4. **Permission keys live in the DB**, not in Keycloak client roles. Each service registers its perms on boot via `RegisterPermissionCatalogUseCase`. Roles are built from those perms in the users service's admin UI.

5. **`AuthenticateTokenUseCase` no longer takes `client_id`.** It only needs a `TokenDecoder` — no more `resource_access` claim extraction.

## Step-by-step

1. **Pin or upgrade**: `pip install pkg-auth>=1.0,<2.0`
2. **Install extras**: `pip install pkg-auth[acl-sqlalchemy,fastapi]` (or `acl-django,django`)
3. **Run the ACL migration** (users service): register `MIGRATIONS_DIR` in Alembic and run `alembic upgrade pkg_auth_acl@head`
4. **Wire the new deps**: `create_authentication(...)`, `make_get_auth_context(...)`, `require_permission(...)`
5. **Replace decorators**: `@require_permissions("foo")` → `Depends(require_permission("foo", get_auth_context=...))`
6. **Declare perms in code** and call `RegisterPermissionCatalogUseCase` on boot
7. **Drop Keycloak claim references**: no more `request.user.realm_roles` / `client_roles`
8. **Update CORS**: add `X-Organization-Id` to `allow_headers`
