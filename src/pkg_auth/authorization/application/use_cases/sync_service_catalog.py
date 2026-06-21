"""Sync the vendor-declared service registry.

This is the **only** path that sets the vendor-controlled flags
``auto_provision`` and ``saas_available`` on a service. Run it from a
deploy-time init container / CLI (``pkg-auth-sync-services``) with a DB
credential that may write the ``services`` table — never from a runtime
API. Runtime service enablement for an org goes through
:class:`SetOrganizationServiceUseCase`, which can only toggle services
already marked ``saas_available`` here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence, Union

from ...config import default_locale
from ...domain.ports import ServiceRepository
from ...domain.value_objects import LocalizedText, ServiceName


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """One row the vendor declares into the service registry."""

    name: ServiceName
    display_label: LocalizedText = field(
        default_factory=lambda: LocalizedText({})
    )
    auto_provision: bool = False
    saas_available: bool = False

    @classmethod
    def make(
        cls,
        name: ServiceName | str,
        display_label: "LocalizedText | Mapping[str, str] | str | None" = None,
        *,
        auto_provision: bool = False,
        saas_available: bool = False,
        default_locale_: str | None = None,
    ) -> "ServiceSpec":
        loc = default_locale_ or default_locale()
        return cls(
            name=name if isinstance(name, ServiceName) else ServiceName(name),
            display_label=LocalizedText.from_input(
                display_label, default_locale=loc
            ),
            auto_provision=auto_provision,
            saas_available=saas_available,
        )


@dataclass(frozen=True, slots=True)
class ServiceSyncResult:
    upserted: int
    pruned: int
    dry_run: bool


@dataclass(slots=True)
class SyncServiceCatalogUseCase:
    """Apply vendor flags to declared services (the overlay model).

    Upserts each declared service's vendor flags (``auto_provision`` /
    ``saas_available``) without clobbering a service-owned ``display_label``.
    Because each service registers its own identity row (via
    ``pkg-auth-sync-catalog``), this does **not** prune by default — a service
    the vendor list omits is simply left ungoverned, not deleted. Pass
    ``prune=True`` for an explicit, central cleanup of services no longer
    declared anywhere.
    """

    service_repo: ServiceRepository

    async def execute(
        self,
        *,
        services: Sequence[ServiceSpec],
        prune: bool = False,
        dry_run: bool = False,
    ) -> ServiceSyncResult:
        keep = [s.name for s in services]

        if dry_run:
            would_prune = 0
            if prune:
                existing = await self.service_repo.list_all()
                existing_names = {str(s.name) for s in existing}
                declared_names = {str(n) for n in keep}
                would_prune = len(existing_names - declared_names)
            return ServiceSyncResult(
                upserted=len(services),
                pruned=would_prune,
                dry_run=True,
            )

        await self.service_repo.upsert_many(services)
        pruned = 0
        if prune:
            pruned = await self.service_repo.prune_absent(keep=keep)
        return ServiceSyncResult(
            upserted=len(services),
            pruned=pruned,
            dry_run=False,
        )
