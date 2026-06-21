"""Sync a service's permission catalog — upsert declared keys, prune absent ones.

Use from a deploy-time init container with a DB credential that has
``INSERT, UPDATE, DELETE`` on ``permissions``. Runtime service credentials
should remain SELECT-only and use :class:`RegisterPermissionCatalogUseCase`
(or nothing at all) instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ...domain.ports import PermissionCatalogRepository, ServiceRepository
from ...domain.value_objects import LocalizedText
from .register_permission_catalog import (
    CatalogEntry,
    CatalogEntryInput,
    _normalize_entry,
)


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Outcome of a catalog sync run.

    For non-dry-runs, ``upserted`` is the number of declared entries
    (all of them are UPSERTed unconditionally by ``register_many``) and
    ``pruned`` is the number of DB rows deleted. For dry-runs, both
    numbers are the *would-be* counts computed from a diff against the
    current DB state; no writes happen.
    """

    upserted: int
    pruned: int
    dry_run: bool


@dataclass(slots=True)
class SyncPermissionCatalogUseCase:
    """Upsert declared entries then delete anything for the service that is
    no longer declared.

    Scoped by ``service_name`` so running sync for ``courses`` will never
    touch permissions owned by other services (e.g. ``users:*``).
    """

    catalog_repo: PermissionCatalogRepository
    service_repo: ServiceRepository | None = None

    async def execute(
        self,
        *,
        service_name: str,
        entries: Sequence[CatalogEntryInput],
        display_label: LocalizedText | None = None,
        dry_run: bool = False,
    ) -> SyncResult:
        normalized: list[CatalogEntry] = [_normalize_entry(e) for e in entries]
        keep_keys = [e.key for e in normalized]

        if dry_run:
            existing = await self.catalog_repo.list_for_service(
                service_name, scope="all"
            )
            existing_keys = {str(p.key) for p in existing}
            declared_keys = {str(k) for k in keep_keys}
            would_prune = existing_keys - declared_keys
            return SyncResult(
                upserted=len(normalized),
                pruned=len(would_prune),
                dry_run=True,
            )

        if self.service_repo is not None:
            await self.service_repo.register_identity(
                name=service_name, display_label=display_label
            )
        await self.catalog_repo.register_many(
            service_name=service_name,
            entries=normalized,
        )
        pruned = await self.catalog_repo.prune_absent(
            service_name=service_name,
            keep_keys=keep_keys,
        )
        return SyncResult(
            upserted=len(normalized),
            pruned=pruned,
            dry_run=False,
        )
