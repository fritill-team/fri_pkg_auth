# itqadem_courses_app — pkg_auth v3.0.0 reference example

A minimal FastAPI service demonstrating the full v3.0.0 wiring of `pkg_auth`:

- `pkg_auth.authentication` (Keycloak JWT validation → `IdentityContext`)
- `pkg_auth.authorization` (per-(user, org) ACL with permission catalog)
- `pkg_auth.authorization.adapters.sqlalchemy` (canonical schema + repos)
- `pkg_auth.authorization.adapters.cache.InMemoryTTLCache` (hot-path cache)
- `pkg_auth.integrations.fastapi` (`create_authentication`, `make_get_auth_context`, `require_permission`)

## Layout

```
itqadem_courses_app/
├── README.md                    (this file)
├── pyproject.toml               (depends on pkg-auth[acl-sqlalchemy,fastapi])
└── courses_app/
    ├── __init__.py
    ├── permissions.py           (the perm keys this service knows about)
    ├── deps.py                  (wires authn + authz + cache)
    ├── main.py                  (FastAPI app + protected routes)
    └── seed.py                  (optional: seed an org/role/membership for local dev)
```

## Quickstart

```bash
# 1. Postgres + Keycloak running locally (docker-compose -d recommended)
# 2. Apply pkg_auth migrations against your ACL database (one-time):
#    Add pkg_auth.authorization.adapters.sqlalchemy.MIGRATIONS_DIR to your
#    Alembic env.py via version_locations, then:
#       alembic upgrade pkg_auth_acl@head
#
# 3. Seed an org / role / membership for the local user:
#    python -m courses_app.seed
#
# 4. Run the service:
#    uvicorn courses_app.main:app --reload
#
# 5. Hit a protected route:
#    curl -H "Authorization: Bearer $TOKEN" \
#         -H "X-Organization-Id: acme" \
#         http://localhost:8000/courses/123
```

## What this example proves end-to-end

1. The service registers its perm catalog on boot (`RegisterPermissionCatalogUseCase`).
2. A request arrives → `Authentication.get_identity` validates the Keycloak JWT.
3. `make_get_auth_context` resolves the local user (Mode A upserts the row via `SyncUserFromJwtUseCase`; Mode B reads it via `ResolveUserFromJwtUseCase`), resolves the org by `X-Organization-Id`, and loads the user's `AuthContext` for that org via the cached membership repo.
4. `require_permission("course:edit")` enforces the perm via `Depends`.
5. Subsequent requests for the same `(user, org)` hit the in-memory cache (30-second TTL by default).

Anything beyond this — admin endpoints for granting roles, the perm catalog UI, etc. — lives in the **users service**, not in pkg_auth and not in this example.
