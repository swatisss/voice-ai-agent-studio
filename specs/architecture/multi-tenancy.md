---
type: Component Spec
title: Multi-tenancy
description: How the tenant is resolved for every request and the isolation rules every query, event and tool call must follow.
status: stable
tags: [architecture, tenancy, security]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Tenant resolution

* Every `/api/*` request carries header `X-Tenant-Id` (the web app sends the tenant chosen in the tenant switcher; `EventSource` and WebSocket requests pass it as query parameter `tenant`).
* Unknown tenant → 404 `tenant_not_found`. Missing tenant → 400 `tenant_required` (except `GET /api/tenants` and `/healthz`).
* v1 has no authentication; the tenant switcher stands in for login ([/product/scope.md](/product/scope.md)).

# Isolation rules

1. Every tenant-owned table has a non-null `tenant_id`; every query filters by it. Repository helpers take `tenant_id` as a required argument.
2. Fetching another tenant's object by id returns 404 (never 403 — do not reveal existence).
3. Agent configs may only reference tools, skills and docs of the same tenant; publish validates this.
4. Knowledge search, clustering and evaluation operate within one tenant and one agent.
5. Events are delivered only to subscribers of the same tenant.
6. Tools always send `X-Tenant-Id`; the mock API serves both demo tenants from separate data sets.

# Acceptance

- **MT-01** — Given an agent of tenant A, when tenant B requests it by id, then the response is 404.
- **MT-02** — Given a request without `X-Tenant-Id` to `/api/agents`, then the response is 400 `tenant_required`.
- **MT-03** — Given tenant B's doc id in tenant A's agent config, when publishing, then publish fails with 422.
- **MT-04** — Given calls in both tenants, when tenant A loads the dashboard, then only tenant A's calls are counted.
