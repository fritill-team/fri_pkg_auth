# Keycloak Admin Provisioning (pkg_auth.admin)

> **v1.0 note:** `--strict-roles` is now optional. When the authorization module (`pkg_auth.authorization`) is in use, per-organization role enforcement is handled by the ACL database rather than by Keycloak client roles. Services that derive authorization from `AuthContext` should omit `--strict-roles`. The Keycloak admin client remains useful for **user provisioning** (creating service accounts, managing invitation flows) and **service-account setup** (client creation, audience configuration).

> This is the **canonical** Keycloak admin documentation for pkg_auth.

This document explains how to use the **Keycloak admin helper** that lives inside the
`pkg_auth.admin` package:

- As a **CLI command** (for Kubernetes initContainers, local scripts, etc.).
- Programmatically **from within your application**.

---

## 1. What this tool does

Given Keycloak admin access (username/password) and some wiring information, the
tool will:

1. Ensure an **API client** exists, typically named:

   ```text
   {APP_NAME or SERVICE_NAME}-api
   ```

2. Ensure a set of **client roles** exist on that API client (usually your
   domain `Permission` values).

3. For each configured **frontend client**:

   - Ensure an **audience protocol mapper** is present so that the API client
     appears in the frontend token `aud` claim.
   - Ensure a **client-roles protocol mapper** exists so that
     `resource_access.{api-client-id}.roles` is available in frontend tokens.

The whole process is **idempotent** – you can run it many times safely.

---

## 2. Required environment variables

The CLI reads configuration from environment variables (via
`settings_from_env()`):

### Required for admin access

- `KEYCLOAK_BASE_URL`
  Example: `https://auth.example.com` (with or without trailing slash)

- `KEYCLOAK_REALM`
  Name of the realm where your clients live (e.g. `Itqadem`)

- `KEYCLOAK_ADMIN_USER`
  Keycloak admin username

- `KEYCLOAK_ADMIN_PASS`
  Keycloak admin password

### Service naming / wiring

- `APP_NAME` or `SERVICE_NAME`
  Used to derive the default API client id:

  ```text
  {APP_NAME or SERVICE_NAME}-api
  ```

  Example: if `APP_NAME=articles`, API client id becomes `articles-api`.

- `KEYCLOAK_FRONTEND_CLIENT_IDS` (optional)
  Comma-separated list of frontend client IDs that should receive:
  - audience mappers
  - client-roles mappers

  Example:

  ```bash
  KEYCLOAK_FRONTEND_CLIENT_IDS="frontend-admin,frontend-student"
  ```

### Optional toggles

- `VERIFY_SSL` (default: `true`)
  Set to `false` to skip TLS verification (not recommended in production).

---

## 3. Installing and exposing the CLI

Assuming your package is called `pkg-auth` and is already installable,
you can expose a console script via `pyproject.toml`:

```toml
[project.scripts]
keycloak-init-client = "pkg_auth.admin.cli:main"
```

After installing the package (e.g. `pip install pkg-auth`), you get
a `keycloak-init-client` command on your PATH. The package already declares
this entry point, so no extra wiring is needed in consuming services.

> There is no `pkg_auth/admin/__main__.py`, so `python -m pkg_auth.admin`
> does **not** work — always invoke the `keycloak-init-client` console script.

---

## 4. CLI usage

The CLI entrypoint lives in `pkg_auth.admin.cli` (`main`).

### Basic usage

```bash
KEYCLOAK_BASE_URL="https://auth.example.com" \
KEYCLOAK_REALM="Itqadem" \
KEYCLOAK_ADMIN_USER="admin" \
KEYCLOAK_ADMIN_PASS="secret" \
APP_NAME="articles" \
KEYCLOAK_FRONTEND_CLIENT_IDS="frontend-admin,frontend-student" \
keycloak-init-client --strict-roles --strict-audience
```

### CLI options

- `--client-id TEXT`
  Override the API client id.
  Default: `{APP_NAME or SERVICE_NAME}-api`.

- `--permissions -P PERM [PERM ...]`
  Explicit list of permission/role names.
  If omitted, you can supply this list from your app via `ensure_keycloak_client_from_env`
  or by calling `provision_keycloak_client` with an explicit list.

- `--frontend-client-ids -F ID [ID ...]`
  Frontend client IDs to which audience + roles mappers will be applied.
  If omitted, falls back to `KEYCLOAK_FRONTEND_CLIENT_IDS` env var.

- `--remove-frontend-client-ids -R ID [ID ...]`
  Frontend clients from which audience + roles mappers will be **removed**
  (only active when `--strict-audience` is set).

- `--strict-roles`
  Reconcile roles strictly:
  - Create missing roles
  - Delete any roles on the API client that are no longer in the desired set.

- `--strict-audience`
  Reconcile audience + roles mappers strictly:
  - Update mapper config if different
  - Remove mappers from `--remove-frontend-client-ids` clients.

The CLI prints a JSON summary to stdout, for example:

```json
{
  "ok": true,
  "client": {
    "id": "e0f3...",
    "clientId": "articles-api",
    "publicClient": false,
    "serviceAccountsEnabled": false,
    "standardFlowEnabled": false,
    "redirectUris": [],
    "webOrigins": [],
    "enabled": true
  },
  "roles": {
    "created": 5,
    "existing": 0
  },
  "audience": [
    {
      "frontend_client": "frontend-admin",
      "created": true,
      "updated": false
    }
  ],
  "client_roles_mapper": [
    {
      "frontend_client": "frontend-admin",
      "created": true,
      "updated": false
    }
  ],
  "removed": []
}
```

If something goes wrong, you get:

```json
{
  "ok": false,
  "error": "Some error message..."
}
```

---

## 5. Programmatic usage inside your app

You have two main options:

### 5.1. Simple env-based helper

If you are happy to configure everything via environment variables, import
the convenience function:

```python
from pkg_auth.admin.env import ensure_keycloak_client_from_env

result = ensure_keycloak_client_from_env(
    strict_roles=True,
    strict_audience=True,
    # Optional overrides:
    # client_id="articles-api",
    # permissions=["articles:create", "articles:read"],
    # frontend_client_ids=["frontend-admin"],
    # remove_frontend_client_ids=["old-frontend"],
)
print(result)
```

This is exactly the same logic as the CLI, but callable from Python.

You might run this in:

- a one-off migration script
- a startup hook
- a Kubernetes `Job`

### 5.2. Full control with settings + client

If you want to construct settings programmatically instead of env vars:

```python
from pkg_auth.admin.settings import KCAdminSettings
from pkg_auth.admin import provision_keycloak_client

settings = KCAdminSettings(
    keycloak_base_url="https://auth.example.com",
    keycloak_admin_user="admin",
    keycloak_admin_pass="secret",
    keycloak_realm="Itqadem",
    verify_ssl=True,
    app_name="articles",
    frontend_client_ids=["frontend-admin"],
)

summary = asyncio.run(
    provision_keycloak_client(
        settings=settings,
        client_id="articles-api",                # optional override
        permissions=["articles:create", "articles:read"],
        frontend_client_ids=["frontend-admin"],  # override env defaults if needed
        strict_roles=True,
        strict_audience=True,
    )
)
print(summary)
```

This gives you full flexibility to drive provisioning from whatever config
system your app uses.

---

## 6. Where this fits in clean architecture

- **`KCAdminSettings`**, **`KeycloakAdminClient`**, and **`provision_keycloak_client`**
  live in a separate `pkg_auth.admin` package, so they do **not**
  pollute your domain model.

- Your app’s domain layer does **not** depend on this admin tooling. It’s
  purely an **infrastructure / operations** concern: “make sure Keycloak is
  configured correctly”.

- You are free to run the CLI or helper functions from:
  - infra repos
  - deployment scripts
  - init containers
  - management commands

…without leaking any of that complexity into your application core.
