"""Register a service's permission catalog at startup."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence, Union

from ...config import default_locale
from ...domain.ports import PermissionCatalogRepository, ServiceRepository
from ...domain.value_objects import (
    LocalizedText,
    PermissionKey,
    PermissionVisibility,
    ServiceName,
)


@dataclass(frozen=True, slots=True)
class ServiceManifest:
    """A service's self-declared identity for the service registry.

    A service ships this alongside its permission catalog so it registers
    *itself* (name + localized ``display_label``) when ``pkg-auth-sync-catalog``
    runs. It deliberately carries no vendor flags (``auto_provision`` /
    ``saas_available``) — those stay vendor-owned via ``pkg-auth-sync-services``.
    """

    name: ServiceName
    display_label: LocalizedText = field(default_factory=lambda: LocalizedText({}))

    @classmethod
    def make(
        cls,
        name: ServiceName | str,
        display_label: "LocalizedText | Mapping[str, str] | str | None" = None,
        *,
        default_locale_: str | None = None,
    ) -> "ServiceManifest":
        loc = default_locale_ or default_locale()
        return cls(
            name=name if isinstance(name, ServiceName) else ServiceName(name),
            display_label=LocalizedText.from_input(
                display_label, default_locale=loc
            ),
        )


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One row a service registers into the central permission catalog.

    ``visibility`` controls which role builders may see/use the permission:

    - ``SHARED`` (default) — usable everywhere.
    - ``PLATFORM_ONLY`` — only the platform org (e.g. ``organizations:create``).
    - ``TENANT_ONLY`` — only normal orgs; hidden from the platform org.

    ``description`` is a :class:`LocalizedText` locale→text map. Build entries
    with :meth:`make` to accept a plain string (stored under the configured
    default locale) or a ``{locale: text}`` dict.
    """

    key: PermissionKey
    description: LocalizedText = field(default_factory=lambda: LocalizedText({}))
    visibility: PermissionVisibility = PermissionVisibility.SHARED

    def __post_init__(self) -> None:
        # Coerce a plain string / dict / None description into LocalizedText
        # so positional ``CatalogEntry(key, "text")`` stays ergonomic.
        if not isinstance(self.description, LocalizedText):
            object.__setattr__(
                self,
                "description",
                LocalizedText.from_input(
                    self.description, default_locale=default_locale()
                ),
            )

    @classmethod
    def make(
        cls,
        key: PermissionKey,
        description: "LocalizedText | Mapping[str, str] | str | None" = None,
        visibility: PermissionVisibility = PermissionVisibility.SHARED,
        *,
        default_locale_: str | None = None,
    ) -> "CatalogEntry":
        """Ergonomic constructor that coerces ``description`` into a
        :class:`LocalizedText` using the configured default locale.
        """
        loc = default_locale_ or default_locale()
        return cls(
            key=key,
            description=LocalizedText.from_input(description, default_locale=loc),
            visibility=visibility,
        )


CatalogEntryInput = Union[
    CatalogEntry,
    tuple[PermissionKey, "LocalizedText | Mapping[str, str] | str | None"],
    tuple[
        PermissionKey,
        "LocalizedText | Mapping[str, str] | str | None",
        PermissionVisibility,
    ],
]


def _normalize_entry(entry: CatalogEntryInput) -> CatalogEntry:
    if isinstance(entry, CatalogEntry):
        return entry
    if isinstance(entry, tuple):
        if len(entry) == 2:
            key, description = entry
            return CatalogEntry.make(key, description)
        if len(entry) == 3:
            key, description, visibility = entry
            return CatalogEntry.make(key, description, visibility)
        raise ValueError(f"Invalid catalog entry tuple length: {len(entry)}")
    raise TypeError(f"Unsupported catalog entry type: {type(entry).__name__}")


@dataclass(slots=True)
class RegisterPermissionCatalogUseCase:
    """Idempotently register the permission keys a service knows about.

    Each consuming service calls this on boot with its static perm
    list. The repository upserts by ``key`` so calling it on every
    restart is safe and converges. Re-registering the same key with a
    different ``visibility`` flips it.

    When a ``service_repo`` is wired, the service registers its own identity
    row (``name`` + optional ``display_label``) with safe default flags, never
    overwriting vendor flags, so the default-deny service guard does not strip
    the service's perms before the vendor configures it.
    """

    catalog_repo: PermissionCatalogRepository
    service_repo: ServiceRepository | None = None

    async def execute(
        self,
        *,
        service_name: str,
        entries: Sequence[CatalogEntryInput],
        display_label: LocalizedText | None = None,
    ) -> None:
        normalized = [_normalize_entry(e) for e in entries]
        if self.service_repo is not None:
            await self.service_repo.register_identity(
                name=service_name, display_label=display_label
            )
        await self.catalog_repo.register_many(
            service_name=service_name,
            entries=normalized,
        )
