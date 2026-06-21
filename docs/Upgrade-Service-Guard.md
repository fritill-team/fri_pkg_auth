# Upgrade guide — service guard, permission visibility, localized descriptions

This documents the **3.0.0** release — a **breaking** change to
`pkg_auth.authorization`.

This release adds five capabilities to `pkg_auth.authorization`:

1. **Permission visibility (tri-state)** — `is_platform: bool` is **replaced**
   by `visibility: PermissionVisibility` with `platform_only` / `shared` /
   `tenant_only`. `tenant_only` perms are hidden from the platform org.
2. **Service registry + service guard** — new `services` and
   `organization_services` tables. A permission is only effective for an org if
   that org has the perm's owning service enabled (**default-deny**).
3. **Default-service auto-provisioning** — services flagged `auto_provision`
   are enabled for every new organization.
4. **Vendor-controlled SaaS governance** — only services the vendor marks
   `saas_available` (via `pkg-auth-sync-services`) can be enabled for an org at
   runtime.
5. **Localized permission descriptions** — `description` is now a JSONB
   `{locale: text}` map; default/fallback locale from `ACL_DEFAULT_LOCALE`
   (fallback `en`).

> **Breaking:** `is_platform` is removed with no alias. Catalogs must switch to
> `visibility=`. Under default-deny, an org with no enabled services resolves
> to **zero permissions** for normal members — provisioning is mandatory.

---

## Mode B (consuming services that use the bundled ORM/migrations)

1. Bump the `pkg-auth` version.
2. Run the bundled migrations (`pkg_auth_acl_0003` … `0005`). If you register
   the bundled `MIGRATIONS_DIR` via `version_locations`, `alembic upgrade head`
   picks them up. Set `ACL_DEFAULT_LOCALE` before migrating so existing
   text descriptions backfill under the right locale.
3. Update any catalog declarations: `is_platform=True` → `visibility=PermissionVisibility.PLATFORM_ONLY`.
4. Wire the guard where you build `ResolveAuthContextUseCase` (see below).

## Mode A (source-of-truth services that own the schema, e.g. `itq_users`)

Mode A owns its migrations and concrete ORM models, so it must absorb the
schema changes itself. The bundled migrations `0003`–`0005` are the reference.

1. **Bump** the `pkg-auth` version.
2. **ORM models** — the new columns flow in through `PermissionMixin`
   (`visibility`, JSONB `description`). Add concrete models for the two new
   tables by subclassing the new mixins:

   ```python
   from pkg_auth.authorization.adapters.sqlalchemy.mixins import (
       ServiceMixin, OrganizationServiceMixin,
   )

   class OrmService(Base, ServiceMixin):
       __tablename__ = "services"
       id = mapped_column(Uuid(as_uuid=True), primary_key=True,
                          server_default=text("gen_random_uuid()"))

   class OrmOrganizationService(Base, OrganizationServiceMixin):
       __tablename__ = "organization_services"
       __table_args__ = (UniqueConstraint("organization_id", "service_name",
                          name="uq_org_services_org_service"),)
       id = mapped_column(Uuid(as_uuid=True), primary_key=True,
                          server_default=text("gen_random_uuid()"))
       organization_id = mapped_column(
           Uuid(as_uuid=True),
           ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
   ```

3. **Migrations** — write service-owned Alembic migrations equivalent to the
   bundled `0003`–`0005`:
   - `permissions`: add `visibility` (default `'shared'`), backfill
     `is_platform=true → 'platform_only'` else `'shared'`, drop `is_platform`;
   - `permissions.description`: `TEXT → JSONB`, backfill non-null text to
     `{ '<ACL_DEFAULT_LOCALE>': <text> }`;
   - create `services` and `organization_services`.

4. **Catalog** — switch entries from `is_platform=` to `visibility=` and
   (optionally) localized descriptions:

   ```python
   CatalogEntry(PermissionKey("organizations:create"), "Create org",
                PermissionVisibility.PLATFORM_ONLY)
   CatalogEntry.make(PermissionKey("course:edit"),
                     {"en": "Edit course", "ar": "تعديل الدورة"})
   ```

5. **Service registry** — ownership is split (the *overlay* model):

   - **Each service registers its own identity** (`name` + `display_label`)
     when it syncs its catalog. Export a `ServiceManifest` next to the catalog
     and pass it to `pkg-auth-sync-catalog --service-manifest`:

     ```python
     # courses/domain/permissions.py
     from pkg_auth.authorization import ServiceManifest, CatalogEntry
     SERVICE = ServiceManifest.make("courses", {"en": "Courses", "ar": "الدورات"})
     CATALOG = [ CatalogEntry.make(...), ... ]
     ```

     ```bash
     pkg-auth-sync-catalog --service courses \
         --catalog courses.domain.permissions:CATALOG \
         --service-manifest courses.domain.permissions:SERVICE \
         --db-url "$ACL_DATABASE_URL"
     ```

   - **The vendor owns only the flags** — `auto_provision` / `saas_available` —
     set via `pkg-auth-sync-services` (this is the *only* path that sets them):

     ```python
     # platform/services.py
     from pkg_auth.authorization import ServiceSpec
     SERVICES = [
         ServiceSpec.make("users", auto_provision=True),
         ServiceSpec.make("assessments", saas_available=True),
         ServiceSpec.make("courses", saas_available=True),
     ]
     ```

     ```bash
     pkg-auth-sync-services --services platform.services:SERVICES \
         --db-url "$ACL_DATABASE_URL"
     ```

   The two paths don't clobber each other: sync-services sets flags without
   overwriting a service-owned `display_label`, and sync-catalog sets the label
   without touching the flags. **sync-services does not prune by default**
   (a service it omits is left ungoverned, not deleted) — pass `--prune` only
   for an explicit central cleanup. Mark core services every org needs (e.g.
   `users`) `auto_provision=True`, otherwise default-deny strips their perms for
   normal orgs.

6. **Provision on org creation** — call `ProvisionDefaultServicesUseCase` from
   your org-creation flow (`app/use_cases/organizations/create_organization.py`):

   ```python
   await ProvisionDefaultServicesUseCase(
       service_repo=service_repo, org_service_repo=org_service_repo,
   ).execute(org_id=organization.id)
   ```

7. **Wire the guard** — pass the guard deps into `ResolveAuthContextUseCase`
   in your dependency factory:

   ```python
   resolve_uc = ResolveAuthContextUseCase(
       membership_repo=membership_repo,
       org_service_repo=CachedOrganizationServiceRepository(
           inner=SqlAlchemyOrganizationServiceRepository(session_factory=sf),
           cache=InMemoryTTLCache(max_entries=10_000), ttl_seconds=30),
       catalog_repo=catalog_repo,
       platform_org_id=cached_platform_org_id,   # platform org bypasses the guard
   )
   ```

   The FastAPI/Django/Strawberry deps need **no change** — the guard is applied
   inside the use case you already pass them. Leaving `org_service_repo`/
   `catalog_repo` unset disables the guard (useful for incremental rollout).

8. **Re-seed** the catalog (`pkg-auth-sync-catalog`) and services
   (`pkg-auth-sync-services`) on deploy.

## SaaS toggle endpoint

Expose `SetOrganizationServiceUseCase` behind a platform-admin endpoint. It
raises `ServiceNotSaaSAvailable` (→ 403) when enabling a service the vendor
hasn't marked `saas_available`, which is how the client is prevented from
offering arbitrary services as SaaS.

## Visibility enforcement

`CreateRoleUseCase` / `UpdateRoleUseCase` accept an optional `platform_org_id`.
When set, they reject assigning `platform_only` perms to a normal-org role and
`tenant_only` perms to a platform-org role (`PermissionVisibilityConflict`).
Pass it for defense beyond the role-builder UI filter (`scope=` on the catalog
repo: `"platform"` → platform_only ∪ shared, `"tenant"`/`"org"` → shared ∪
tenant_only).
