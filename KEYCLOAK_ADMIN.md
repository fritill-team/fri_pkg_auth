# Keycloak Admin Provisioning (stub)

The Keycloak admin helper lives in the `pkg_auth.admin` package. It idempotently
ensures an API client, its client roles, and the audience / client-roles
protocol mappers on your frontend clients exist — useful from Kubernetes
initContainers, deployment scripts, or programmatically from your app. The
console command is **`keycloak-init-client`** (entry point
`pkg_auth.admin.cli:main`).

> The canonical, full documentation is **[docs/Keycloak-Admin.md](./docs/Keycloak-Admin.md)** —
> see it for environment variables, CLI options, and programmatic usage.
