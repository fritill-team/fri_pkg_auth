"""SQLAlchemy implementation of ServiceRepository (UUID PKs, injectable model)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ....application.use_cases.sync_service_catalog import ServiceSpec
from ....domain.entities import Service
from ....domain.value_objects import LocalizedText, ServiceName
from ..models import ServiceORM as DefaultServiceORM


def _to_service(row: Any) -> Service:
    return Service(
        name=ServiceName(row.name),
        display_label=LocalizedText(row.display_label or {}),
        auto_provision=bool(row.auto_provision),
        saas_available=bool(row.saas_available),
        created_at=row.created_at,
    )


@dataclass(slots=True)
class SqlAlchemyServiceRepository:
    session_factory: async_sessionmaker[AsyncSession]
    model: type = field(default=DefaultServiceORM)

    async def upsert_many(self, services: Sequence[ServiceSpec]) -> None:
        """Vendor flag overlay: set ``auto_provision`` / ``saas_available``.

        On insert the spec's ``display_label`` seeds the row; on conflict the
        existing (service-owned) label is preserved — only the flags update.
        """
        if not services:
            return
        rows = [
            {
                "name": str(s.name),
                "display_label": s.display_label.as_dict() or None,
                "auto_provision": s.auto_provision,
                "saas_available": s.saas_available,
            }
            for s in services
        ]
        stmt = pg_insert(self.model).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={
                "auto_provision": stmt.excluded.auto_provision,
                "saas_available": stmt.excluded.saas_available,
            },
        )
        async with self.session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def register_identity(
        self, *, name: str, display_label: LocalizedText | None = None
    ) -> None:
        """Self-register a service's identity; never overwrite vendor flags.

        Inserts a row with safe default flags if absent. If a non-empty
        ``display_label`` is given, it is set on insert and on conflict
        (identity is service-owned); the flags are left untouched.
        """
        label = display_label.as_dict() if display_label is not None else None
        stmt = pg_insert(self.model).values(
            name=name,
            display_label=label or None,
            auto_provision=False,
            saas_available=False,
        )
        if label:
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={"display_label": stmt.excluded.display_label},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=["name"])
        async with self.session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def get(self, name: ServiceName) -> Service | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(self.model).where(self.model.name == str(name))
                )
            ).scalar_one_or_none()
            return _to_service(row) if row is not None else None

    async def list_all(self) -> list[Service]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(select(self.model).order_by(self.model.name))
            ).scalars().all()
            return [_to_service(r) for r in rows]

    async def prune_absent(self, *, keep: Iterable[ServiceName]) -> int:
        names = [str(n) for n in keep]
        stmt = delete(self.model)
        if names:
            stmt = stmt.where(self.model.name.notin_(names))
        async with self.session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)
