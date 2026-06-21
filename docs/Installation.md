# Installation

## Install from PyPI

```bash
pip install pkg-auth
```

The core install ships authentication only (no DB dependencies). Pull in the
ACL, a framework integration, or caching with extras:

```bash
# ACL (SQLAlchemy) + FastAPI — the common combination
pip install "pkg-auth[acl-sqlalchemy,fastapi]"
```

Available extras:

| Extra | Pulls in |
|---|---|
| `acl-sqlalchemy` | SQLAlchemy ACL adapter + Alembic migrations |
| `acl-django` | Django ORM ACL adapter |
| `cache-redis` | Redis cache backend |
| `fastapi` | FastAPI integration |
| `django` | Django integration |
| `strawberry` | Strawberry GraphQL integration |
| `all` | Everything above |

```bash
pip install "pkg-auth[all]"
```

## Localized descriptions

Permission descriptions are stored as a localized JSONB map. The default locale
used when a bare string is supplied is read from the `ACL_DEFAULT_LOCALE`
environment variable (default `en`).

## Fallback: install from GitHub

If you need a build that is not on PyPI yet, install directly from the
repository at a package tag:

```bash
pip install "pkg-auth @ git+https://github.com/fritill-team/fri_pkg_auth.git@pkg_auth-v3.0.0"
```

Extras work the same way:

```bash
pip install "pkg-auth[acl-sqlalchemy,fastapi] @ git+https://github.com/fritill-team/fri_pkg_auth.git@pkg_auth-v3.0.0"
```

Monorepo note: if the package lives in a subdirectory, append
`#subdirectory=path/to/pkg` to the URL.

## Fallback: install a Release wheel

For a public repo you can install the wheel directly from the Release page:

```bash
pip install "https://github.com/fritill-team/fri_pkg_auth/releases/download/pkg_auth-v3.0.0/pkg_auth-3.0.0-py3-none-any.whl"
```

Use the exact wheel filename shown on the Release; project names typically use
underscores (`pkg_auth-...`).
