# Strawberry GraphQL Integration

## Setup (Mode B — consumer, the common case)

```python
from pkg_auth.authorization.application.use_cases.resolve_user_from_jwt import (
    ResolveUserFromJwtUseCase,
)
from pkg_auth.integrations.strawberry import (
    make_context_getter, IsAuthenticated, RequirePermission,
)

context_getter = make_context_getter(
    authenticate_use_case=authenticate_uc,
    resolve_user_use_case=ResolveUserFromJwtUseCase(   # Mode B — reader
        user_repo=user_repo,
    ),
    resolve_use_case=resolve_uc,
    organization_repo=org_repo,
)

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema, context_getter=context_getter)
```

`resolve_uc` is a `ResolveAuthContextUseCase(membership_repo=...)`. To enable
the optional **service guard** (default-deny: resolved perms are filtered to the
services the org has enabled), also pass `org_service_repo=`, `catalog_repo=`,
and `platform_org_id=` (the platform org bypasses the guard):

```python
from pkg_auth.authorization.application.use_cases.resolve_auth_context import (
    ResolveAuthContextUseCase,
)

resolve_uc = ResolveAuthContextUseCase(
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

Mode A (source-of-truth) services pass `sync_user_use_case=SyncUserFromJwtUseCase(...)`
instead. The two parameters are mutually exclusive; the Strawberry
context getter is permissive, so a `UserNotProvisioned` miss in Mode B
degrades `ctx.auth_context` to `None` rather than raising —
permission classes (e.g. `RequirePermission`) then reject the query.

## Permission classes

```python
@strawberry.type
class Query:
    @strawberry.field(permission_classes=[IsAuthenticated])
    async def me(self, info: Info) -> str:
        return info.context.identity.subject_str

    @strawberry.field(permission_classes=[RequirePermission("course:view")])
    async def course(self, id: strawberry.ID, info: Info) -> Course:
        ...
```

## Context object

Every resolver receives a `StrawberryContext` via `info.context`:

```python
@dataclass
class StrawberryContext:
    request: Request
    identity: IdentityContext | None
    auth_context: AuthContext | None
    extra: dict[str, object]
```

- `identity` is `None` when no valid JWT is present.
- `auth_context` is `None` when `X-Organization-Id` header is missing, the user isn't a member, or (Mode B) the user hasn't been provisioned into the ACL by the source-of-truth yet.
- The context getter is permissive (no exceptions raised) — permission classes decide what to reject.
