"""Django ORM implementation of ServiceRepository."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ....application.use_cases.sync_service_catalog import ServiceSpec
from ....domain.entities import Service
from ....domain.value_objects import LocalizedText, ServiceName
from ..models import Service as DefaultServiceModel


def _to_domain(row) -> Service:
    return Service(
        name=ServiceName(row.name),
        display_label=LocalizedText(row.display_label or {}),
        auto_provision=bool(row.auto_provision),
        saas_available=bool(row.saas_available),
        created_at=row.created_at,
    )


@dataclass(slots=True)
class DjangoServiceRepository:
    model: type = field(default=DefaultServiceModel)

    async def upsert_many(self, services: Sequence[ServiceSpec]) -> None:
        """Vendor flag overlay: set flags, seed label only on create.

        On conflict the existing (service-owned) ``display_label`` is preserved
        — only the vendor flags update. Written without ``create_defaults`` so
        it works on Django 4.2.
        """
        for s in services:
            obj, created = await self.model.objects.aget_or_create(
                name=str(s.name),
                defaults={
                    "display_label": s.display_label.as_dict() or None,
                    "auto_provision": s.auto_provision,
                    "saas_available": s.saas_available,
                },
            )
            if not created:
                obj.auto_provision = s.auto_provision
                obj.saas_available = s.saas_available
                await obj.asave(
                    update_fields=["auto_provision", "saas_available"]
                )

    async def register_identity(
        self, *, name: str, display_label: LocalizedText | None = None
    ) -> None:
        """Self-register identity; never overwrite vendor flags."""
        label = display_label.as_dict() if display_label is not None else None
        obj, created = await self.model.objects.aget_or_create(
            name=name,
            defaults={
                "display_label": label or None,
                "auto_provision": False,
                "saas_available": False,
            },
        )
        if not created and label:
            obj.display_label = label
            await obj.asave(update_fields=["display_label"])

    async def get(self, name: ServiceName) -> Service | None:
        row = await self.model.objects.filter(name=str(name)).afirst()
        return _to_domain(row) if row is not None else None

    async def list_all(self) -> list[Service]:
        return [
            _to_domain(r)
            async for r in self.model.objects.order_by("name")
        ]

    async def prune_absent(self, *, keep: Iterable[ServiceName]) -> int:
        names = [str(n) for n in keep]
        qs = self.model.objects.all()
        if names:
            qs = qs.exclude(name__in=names)
        deleted, _ = await qs.adelete()
        return int(deleted)
