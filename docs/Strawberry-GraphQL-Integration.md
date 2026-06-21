# Strawberry GraphQL Integration (stub)

> The canonical Strawberry guide is **[docs/Strawberry.md](./Strawberry.md)**. It
> covers Mode A vs Mode B wiring, permission classes, the `StrawberryContext`
> object, and the optional service guard. This page is a short pointer kept for
> backwards-compatible links.

## Minimal current example

```python
import strawberry
from strawberry.fastapi import GraphQLRouter
from pkg_auth.integrations.strawberry import (
    make_context_getter, IsAuthenticated, RequirePermission,
)

context_getter = make_context_getter(
    authenticate_use_case=authenticate_uc,
    resolve_user_use_case=resolve_user_uc,   # Mode B — reader
    resolve_use_case=resolve_uc,
    organization_repo=org_repo,
)

@strawberry.type
class Query:
    @strawberry.field(permission_classes=[IsAuthenticated])
    async def me(self, info) -> str:
        return info.context.identity.subject_str

    @strawberry.field(permission_classes=[RequirePermission("course:view")])
    async def course(self, id: strawberry.ID, info) -> Course:
        auth_ctx = info.context.auth_context
        ...

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema, context_getter=context_getter)
```

Every resolver receives a `StrawberryContext` via `info.context` with
`identity` and `auth_context` fields. See [docs/Strawberry.md](./Strawberry.md)
for the full reference.
