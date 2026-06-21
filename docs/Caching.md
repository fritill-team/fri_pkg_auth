# Caching

The authorization hot path (`load_auth_context`) runs on every protected request. Without caching, this is a Postgres query (joined across `memberships`, `roles`, `role_permissions`, `permissions`). The cache layer eliminates repeated queries for the same `(user, org)` pair within a short TTL window.

## Architecture

```
CachedMembershipRepository  (decorator — implements MembershipRepository)
├── inner: SqlAlchemyMembershipRepository  (the real DB)
└── cache: Cache  (Protocol — InMemoryTTLCache or RedisCache)

CachedOrganizationServiceRepository  (decorator — implements OrganizationServiceRepository)
├── inner: SqlAlchemyOrganizationServiceRepository  (the real DB)
└── cache: Cache  (Protocol — InMemoryTTLCache or RedisCache)
```

Both decorators live in `pkg_auth.authorization.adapters.cache` alongside the
`Cache` protocol and its `InMemoryTTLCache` / `RedisCache` backends.

## Usage

```python
from pkg_auth.authorization.adapters.cache import (
    CachedMembershipRepository, InMemoryTTLCache,
)

inner = SqlAlchemyMembershipRepository(session_factory=session_factory)
cache = InMemoryTTLCache(max_entries=10_000)
membership_repo = CachedMembershipRepository(
    inner=inner, cache=cache, ttl_seconds=30,
)
```

For Redis:

```python
import redis.asyncio as redis
from pkg_auth.authorization.adapters.cache import (
    CachedMembershipRepository, RedisCache,
)

client = redis.from_url("redis://localhost:6379/0")
membership_repo = CachedMembershipRepository(
    inner=SqlAlchemyMembershipRepository(session_factory=session_factory),
    cache=RedisCache(client=client, namespace="pkg_auth:acl"),
    ttl_seconds=60,
)
```

## Cache invalidation

| Operation | Invalidation |
|---|---|
| `upsert` (membership) | Auto — the decorator deletes the `(user, org)` key |
| `delete` (membership) | Auto — same |
| `update_role` (perms change) | **Manual** — the calling use case must call `cache.invalidate_prefix("auth_ctx:")` |

Role-level changes affect potentially many cached entries. The package does NOT auto-invalidate them because guessing wrong would silently serve stale perms. Document this in your service's role-update endpoint.

## Caching the service guard (`CachedOrganizationServiceRepository`)

The default-deny service guard (`ResolveAuthContextUseCase` with an
`org_service_repo`) calls `list_enabled_service_names(org_id)` on every protected
request to decide which permissions survive. `CachedOrganizationServiceRepository`
wraps an `OrganizationServiceRepository` and caches that per-org enabled-service-name
set under the key `org_services:{org_id}` for `ttl_seconds`.

```python
from pkg_auth.authorization.adapters.cache import (
    CachedOrganizationServiceRepository, InMemoryTTLCache,
)

org_service_repo = CachedOrganizationServiceRepository(
    inner=SqlAlchemyOrganizationServiceRepository(session_factory=session_factory),
    cache=InMemoryTTLCache(max_entries=10_000),
    ttl_seconds=30,
)
```

The decorator auto-invalidates the `org_services:{org_id}` key on `enable`,
`disable`, and `bulk_enable`, so toggling an org's entitlements is reflected
immediately. Pass it as the `org_service_repo` to `ResolveAuthContextUseCase`
to keep the service-guard hot path off the database.

## Custom backends

Implement the `Cache` Protocol (bytes-in/bytes-out: `get`, `set`, `delete`, `invalidate_prefix`) and pass your implementation to `CachedMembershipRepository`.

## CORS

If your service uses CORS middleware, add `X-Organization-Id` to `allow_headers` — otherwise preflight requests for the org header will be blocked.
