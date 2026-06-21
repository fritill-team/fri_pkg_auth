"""``pkg-auth-sync-services`` — deploy-time service registry sync.

The **vendor-only** path that declares which services exist and sets their
``auto_provision`` / ``saas_available`` flags. Run from an init container
with a DB credential that may write the ``services`` table. The runtime
SaaS-toggle endpoint (:class:`SetOrganizationServiceUseCase`) can only
enable services this CLI has marked ``saas_available``.

The declared config is a dotted ``module:ATTR`` resolving to a sequence of
:class:`ServiceSpec` (build them with ``ServiceSpec.make`` for ergonomic
localized labels):

    SERVICES = [
        ServiceSpec.make("users", {"en": "Users"}, auto_provision=True),
        ServiceSpec.make("assessments", {"en": "Assessments"},
                         saas_available=True),
    ]

Composable pieces (``build_arg_parser``, ``load_services``, ``run``) mirror
``sync_catalog`` so services can assemble custom entrypoints.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from typing import Awaitable, Callable, Sequence

from ..application.use_cases.sync_service_catalog import (
    ServiceSpec,
    ServiceSyncResult,
    SyncServiceCatalogUseCase,
)
from ..domain.ports import ServiceRepository

ServicesLoader = Callable[[str], Sequence[ServiceSpec]]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pkg-auth-sync-services",
        description=(
            "Sync the vendor service registry against the ACL database: "
            "UPSERT declared services (name, label, auto_provision, "
            "saas_available), DELETE services no longer declared."
        ),
    )
    parser.add_argument(
        "--services",
        required=True,
        help=(
            "Dotted path to the service-spec iterable, e.g. "
            "'platform.services:SERVICES'."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("ACL_DATABASE_URL"),
        help=(
            "SQLAlchemy async DB URL for the ACL database. "
            "Falls back to the ACL_DATABASE_URL env var."
        ),
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "Also DELETE services not in this list. Off by default (overlay "
            "model: services own their own identity rows). Use only for an "
            "explicit central cleanup."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write. Print what would be upserted / pruned and exit 0.",
    )
    return parser


def load_services(dotted: str) -> list[ServiceSpec]:
    """Resolve ``module.path:ATTR`` to a list of :class:`ServiceSpec`."""
    if ":" not in dotted:
        raise ValueError(f"Expected 'module.path:ATTR', got {dotted!r}")
    module_path, attr = dotted.split(":", 1)
    module = importlib.import_module(module_path)
    try:
        value = getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(
            f"Module {module_path!r} has no attribute {attr!r}"
        ) from exc
    return list(value)


async def run(
    args: argparse.Namespace,
    *,
    repo: ServiceRepository | None = None,
    session_factory: object | None = None,
    services_loader: ServicesLoader = load_services,
) -> ServiceSyncResult:
    dispose: Callable[[], Awaitable[None]] | None = None
    if repo is None:
        from sqlalchemy.ext.asyncio import (  # noqa: PLC0415
            async_sessionmaker,
            create_async_engine,
        )

        from ..adapters.sqlalchemy.repositories.service import (  # noqa: PLC0415
            SqlAlchemyServiceRepository,
        )

        if session_factory is None:
            if not args.db_url:
                raise SystemExit(
                    "--db-url is required (or set ACL_DATABASE_URL)"
                )
            engine = create_async_engine(args.db_url, future=True)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            dispose = engine.dispose
        repo = SqlAlchemyServiceRepository(session_factory=session_factory)

    services = services_loader(args.services)
    use_case = SyncServiceCatalogUseCase(service_repo=repo)

    if args.dry_run:
        existing = {str(s.name) for s in await repo.list_all()}
        declared = {str(s.name) for s in services}
        print(f"[dry-run] to add:   {sorted(declared - existing)}")
        if args.prune:
            print(f"[dry-run] to prune: {sorted(existing - declared)}")

    try:
        result = await use_case.execute(
            services=services, prune=args.prune, dry_run=args.dry_run
        )
    finally:
        if dispose is not None:
            await dispose()
    return result


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"pkg-auth-sync-services: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(
        f"sync-services: upserted={result.upserted} "
        f"pruned={result.pruned} dry_run={result.dry_run}"
    )


if __name__ == "__main__":
    main()
