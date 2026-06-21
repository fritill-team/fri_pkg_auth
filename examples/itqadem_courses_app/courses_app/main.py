"""FastAPI app demonstrating identity + ACL on a few protected routes."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from pkg_auth.authentication import IdentityContext
from pkg_auth.authorization import AuthContext

from .deps import (
    configure_app,
    get_auth_context,
    register_catalog_use_case,
    require_permission,
)
from .permissions import CATALOG, SERVICE_NAME


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register this service's perm catalog on boot. Idempotent — safe
    # to call on every restart.
    await register_catalog_use_case.execute(
        service_name=SERVICE_NAME,
        entries=[(key, desc) for key, desc in CATALOG],
    )
    yield


app = FastAPI(
    title="itqadem courses",
    version="0.1.0",
    lifespan=lifespan,
)
configure_app(app)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/me")
async def me(
    bundle: tuple[IdentityContext, AuthContext] = Depends(get_auth_context),
):
    """Return the active identity + role for the current org."""
    identity, auth_ctx = bundle
    return {
        "subject": identity.subject_str,
        "email": identity.email_str,
        "org_id": str(auth_ctx.organization_id),
        "roles": sorted(auth_ctx.role_names),
        "perms": sorted(auth_ctx.perms),
    }


@app.get("/courses/{course_id}")
async def get_course(
    course_id: str,
    bundle: tuple[IdentityContext, AuthContext] = Depends(
        require_permission("course:view", get_auth_context=get_auth_context)
    ),
):
    """Read a course — requires ``course:view``."""
    _, auth_ctx = bundle
    return {
        "course_id": course_id,
        "org_id": str(auth_ctx.organization_id),
        "roles": sorted(auth_ctx.role_names),
    }


@app.post("/courses/{course_id}/publish")
async def publish_course(
    course_id: str,
    bundle: tuple[IdentityContext, AuthContext] = Depends(
        require_permission("course:publish", get_auth_context=get_auth_context)
    ),
):
    """Publish a course — requires ``course:publish``."""
    identity, auth_ctx = bundle
    return {
        "course_id": course_id,
        "published_by": identity.subject_str,
        "org_id": str(auth_ctx.organization_id),
    }


@app.delete(
    "/courses/{course_id}",
    dependencies=[
        Depends(require_permission("course:delete", get_auth_context=get_auth_context))
    ],
)
async def delete_course(course_id: str):
    """Delete a course — requires ``course:delete`` (route-level dep style)."""
    return {"deleted": course_id}
