# Welcome to pkg-auth

`pkg-auth` is a clean-architecture **identity + ACL** core for multi-framework
Python services. It validates Keycloak JWTs and resolves database-backed
authorization (users, organizations, roles, permissions, memberships, services)
into a hot-path context your handlers can check. First-class integrations exist
for **FastAPI**, **Django**, and **Strawberry GraphQL**.

Distribution: `pkg-auth` (`pip install pkg-auth`) · import `pkg_auth` ·
repo [fritill-team/fri_pkg_auth](https://github.com/fritill-team/fri_pkg_auth).

## The two modules

- **`pkg_auth.authentication`** — validates a Keycloak JWT and produces an
  `IdentityContext` (who the caller is; identity only, no DB).
- **`pkg_auth.authorization`** — the ACL: users, organizations, roles,
  permissions, memberships, and services. Resolves a request into an
  `AuthContext` (`user_id`, `organization_id`, `role_names`, `perms`).

## The ACL model

Permissions use `resource:action` keys held in a global catalog. Each catalog
entry carries a tri-state **visibility** (`platform_only` / `shared` /
`tenant_only`) and a localized JSONB **description**. Roles bind permissions;
memberships bind a user to a role within an organization. A first-class
**Service** registry plus per-org **OrganizationService** entitlements drive a
**default-deny service guard** (the platform org bypasses it). See
[Authorization](Authorization).

## Mode A vs Mode B

- **Mode A (source of truth)** — your service owns the `users` table, extends the
  bundled mixins, applies the schema, and lazily upserts users with
  `SyncUserFromJwtUseCase`.
- **Mode B (consumer)** — your service reads the shared ACL read-only and uses
  `ResolveUserFromJwtUseCase` (403s if the user is not provisioned).

## Integrations

- **[FastAPI](FastAPI)** — dependencies + `require_permission` + exception handlers.
- **[Django](Django)** — middleware + decorators.
- **[Strawberry](Strawberry)** — context getter + permission classes.

## Features

- Keycloak JWT authentication.
- Database-backed RBAC with multi-role membership.
- Permission **visibility** (tri-state) and **localized descriptions**.
- First-class **Services** and a **default-deny service guard**.
- Optional in-process or Redis caching.
- CLIs: `keycloak-init-client`, `pkg-auth-sync-catalog`, `pkg-auth-sync-services`.

## Getting started

- **[Installation](Installation)** — PyPI install and extras.
- **[User Guide](User-Guide)** — core concepts and protecting routes.
- **[Authorization](Authorization)** — schema, catalog, roles, service guard.
- **[Upgrade to the Service Guard](Upgrade-Service-Guard)** — the 3.0.0 upgrade.
- **[Caching](Caching)** — cache backends and invalidation.
- **[Keycloak Admin](Keycloak-Admin)** — user provisioning.
