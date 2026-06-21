# FastAPI Integration (stub)

> The canonical FastAPI guide is **[docs/FastAPI.md](./FastAPI.md)**. It covers
> Mode A vs Mode B wiring, route protection, error mapping, and the optional
> service guard. This page is a short pointer kept for backwards-compatible links.

## Minimal current example

```python
from pkg_auth.authorization.application.use_cases.resolve_user_from_jwt import (
    ResolveUserFromJwtUseCase,
)
from pkg_auth.authorization.application.use_cases.resolve_auth_context import (
    ResolveAuthContextUseCase,
)
from pkg_auth.integrations.fastapi import (
    create_authentication, make_get_auth_context, require_permission,
)

auth = create_authentication(
    keycloak_base_url="https://auth.example.com",
    realm="itqadem",
    audience="courses-service",
)
get_auth_context = make_get_auth_context(
    get_identity=auth.get_identity,
    resolve_user_use_case=ResolveUserFromJwtUseCase(user_repo=user_repo),  # Mode B
    resolve_use_case=ResolveAuthContextUseCase(membership_repo=membership_repo),
    organization_repo=org_repo,
)

@router.get("/courses/{id}")
async def get_course(
    id: str,
    bundle=Depends(require_permission("course:view", get_auth_context=get_auth_context)),
):
    identity, auth_ctx = bundle
    ...
```

See [docs/FastAPI.md](./FastAPI.md) for the full reference.
