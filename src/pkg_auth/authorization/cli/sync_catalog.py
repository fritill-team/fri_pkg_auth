"""``pkg-auth-sync-catalog`` — deploy-time permission catalog sync.

Intended for an init container that runs with a DB credential holding
``INSERT, UPDATE, DELETE`` on ``permissions`` only. The long-running
service should keep a separate SELECT-only credential and never call
this CLI.

Public surface is factored so services that want to customize something
(extra flags, a different catalog loader, a pre-built session factory)
can import the pieces and assemble their own entrypoint:

    from pkg_auth.authorization.cli.sync_catalog import (
        build_arg_parser, load_catalog, run,
    )

    def main() -> None:
        parser = build_arg_parser()
        parser.add_argument("--skip-legacy", action="store_true")
        args = parser.parse_args()
        asyncio.run(run(args, catalog_loader=my_loader))
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from typing import Awaitable, Callable, Sequence

from ..application.use_cases.register_permission_catalog import (
    CatalogEntry,
    ServiceManifest,
)
from ..application.use_cases.sync_permission_catalog import (
    SyncPermissionCatalogUseCase,
    SyncResult,
)
from ..domain.ports import PermissionCatalogRepository, ServiceRepository

CatalogLoader = Callable[[str], Sequence[CatalogEntry]]
ManifestLoader = Callable[[str], ServiceManifest]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pkg-auth-sync-catalog",
        description=(
            "Sync a service's permission catalog against the ACL database: "
            "UPSERT declared entries, DELETE anything for the service that "
            "is no longer declared."
        ),
    )
    parser.add_argument(
        "--service",
        required=True,
        help="Service name whose catalog rows are managed by this run.",
    )
    parser.add_argument(
        "--catalog",
        required=True,
        help=(
            "Dotted path to the catalog iterable, e.g. "
            "'courses.domain.permissions:CATALOG'."
        ),
    )
    parser.add_argument(
        "--service-manifest",
        default=None,
        help=(
            "Optional dotted path to a ServiceManifest the service registers "
            "for itself, e.g. 'courses.domain.permissions:SERVICE'. Its name "
            "must match --service; its display_label seeds/updates the "
            "service's identity row. Vendor flags stay owned by "
            "pkg-auth-sync-services."
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
        "--dry-run",
        action="store_true",
        help=(
            "Do not write. Print what would be upserted / pruned and exit 0."
        ),
    )
    return parser


def load_catalog(dotted: str) -> list[CatalogEntry]:
    """Resolve ``module.path:ATTR`` to a list of :class:`CatalogEntry`."""
    if ":" not in dotted:
        raise ValueError(
            f"Expected 'module.path:ATTR', got {dotted!r}"
        )
    module_path, attr = dotted.split(":", 1)
    module = importlib.import_module(module_path)
    try:
        value = getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(
            f"Module {module_path!r} has no attribute {attr!r}"
        ) from exc
    return list(value)


def load_manifest(dotted: str) -> ServiceManifest:
    """Resolve ``module.path:ATTR`` to a :class:`ServiceManifest`."""
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
    if not isinstance(value, ServiceManifest):
        raise ValueError(
            f"{dotted!r} is not a ServiceManifest (got "
            f"{type(value).__name__})"
        )
    return value


async def run(
    args: argparse.Namespace,
    *,
    repo: PermissionCatalogRepository | None = None,
    service_repo: ServiceRepository | None = None,
    session_factory: object | None = None,
    catalog_loader: CatalogLoader = load_catalog,
    manifest_loader: ManifestLoader = load_manifest,
) -> SyncResult:
    dispose: Callable[[], Awaitable[None]] | None = None
    if repo is None:
        from sqlalchemy.ext.asyncio import (  # noqa: PLC0415
            async_sessionmaker,
            create_async_engine,
        )

        from ..adapters.sqlalchemy.repositories.permission_catalog import (  # noqa: PLC0415
            SqlAlchemyPermissionCatalogRepository,
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
        repo = SqlAlchemyPermissionCatalogRepository(
            session_factory=session_factory
        )
        if service_repo is None:
            service_repo = SqlAlchemyServiceRepository(
                session_factory=session_factory
            )

    entries = catalog_loader(args.catalog)

    display_label = None
    if args.service_manifest:
        manifest = manifest_loader(args.service_manifest)
        if str(manifest.name) != args.service:
            raise SystemExit(
                f"manifest name {str(manifest.name)!r} does not match "
                f"--service {args.service!r}"
            )
        display_label = manifest.display_label

    use_case = SyncPermissionCatalogUseCase(
        catalog_repo=repo, service_repo=service_repo
    )

    if args.dry_run:
        existing = await repo.list_for_service(args.service, scope="all")
        existing_keys = {str(p.key) for p in existing}
        declared_keys = {str(e.key) for e in entries}
        to_add = sorted(declared_keys - existing_keys)
        to_prune = sorted(existing_keys - declared_keys)
        print(f"[dry-run] service={args.service}")
        print(f"[dry-run] to add:   {to_add}")
        print(f"[dry-run] to prune: {to_prune}")

    try:
        result = await use_case.execute(
            service_name=args.service,
            entries=entries,
            display_label=display_label,
            dry_run=args.dry_run,
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
        print(f"pkg-auth-sync-catalog: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(
        f"sync: service={args.service} upserted={result.upserted} "
        f"pruned={result.pruned} dry_run={result.dry_run}"
    )


if __name__ == "__main__":
    main()
