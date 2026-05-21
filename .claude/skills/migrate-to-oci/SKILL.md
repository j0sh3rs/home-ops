---
name: migrate-to-oci
description: Migrate a legacy home-ops app from `HelmRepository` + `chart.spec.sourceRef` to `OCIRepository` + `chartRef`. Validates OCI availability, rewrites HelmRelease + repo files, verifies with kustomize + flux build. Use when user says "migrate to OCI", "convert to OCIRepository", "remove legacy sourceRef", or invokes /migrate-to-oci.
---

# migrate-to-oci (home-ops)

Convert one legacy Helm chart app at a time to the OCIRepository + chartRef pattern. Destructive (rewrites committed files) — run one app per invocation and confirm each step.

## Legacy apps pending migration

Per `CLAUDE.md`, these are known candidates (verify before starting — list may be stale):

- `kubernetes/apps/cert-manager/cert-manager/`
- `kubernetes/apps/databases/cloudnative-pg/` — OCI: `ghcr.io/cloudnative-pg/charts`
- `kubernetes/apps/databases/dragonflydb/` — hybrid: already `oci://` URL under `HelmRepository` kind → switch to `OCIRepository`
- `kubernetes/apps/velero/`
- `kubernetes/apps/kube-system/amd-gpu/`
- `kubernetes/apps/kube-system/descheduler/` — OCI: `ghcr.io/kubernetes-sigs/descheduler`
- `kubernetes/apps/kube-system/nfs-external-provisioner/`
- `kubernetes/apps/kube-system/tetragon/`

Reference examples: check `kubernetes/flux/meta/repos/` for existing OCIRepository definitions to mirror their structure.

## Usage

- `/migrate-to-oci` — prompt for target app
- `/migrate-to-oci kubernetes/apps/<ns>/<app>` — direct

## Workflow

### Stage 1 — inspect target

```bash
# Identify current chart + HelmRepository
rg -A 8 "chart:" kubernetes/apps/<ns>/<app>/app/helmrelease.yaml
rg -l "name: <helm-repo-name>" kubernetes/flux/meta/repos/
```

Capture:
- Chart name (`chart.spec.chart`)
- Current version (`chart.spec.version`)
- HelmRepository name + URL
- Whether the HelmRepository is shared with other apps

### Stage 2 — probe for OCI equivalent

Priority probe order:

1. **GHCR at the org that publishes the chart**: `oci://ghcr.io/<org>/charts/<chart-name>` or `oci://ghcr.io/<org>/<chart-name>`
2. **Docker Hub**: `oci://registry-1.docker.io/<org>/<chart-name>`
3. **Upstream project docs**: check GitHub README for `helm install oci://...` guidance

```bash
# Verify an OCI tag exists before committing to it
curl -sfLI "https://ghcr.io/v2/<org>/<path>/manifests/<tag>" >/dev/null && echo "OCI OK" || echo "Not available"
```

If no OCI artifact exists, ABORT. Report back to user — do not force migration. Some charts still only publish via HelmRepository (cert-manager pre-OCI versions were an example).

### Stage 3 — confirm plan with user

Before editing anything, show user a 4-line plan:

```
Migrate: <ns>/<app>
From:    HelmRepository <name> → chart <chart>:<version>
To:      OCIRepository  → url oci://<path>  tag <version>
Shared repo file: <delete | keep (used by: <other-apps>)>
```

Wait for yes/no.

### Stage 4 — rewrite HelmRelease

Two options; pick based on how the app repo is organized today:

**Option A — embed OCIRepository alongside HelmRelease** (simpler; matches most app-template apps):
- In `kubernetes/apps/<ns>/<app>/app/helmrelease.yaml`:
  - Add `OCIRepository` resource at top (same anchor/name as app)
  - Rewrite `HelmRelease` body: remove `spec.chart.spec.*`, add `spec.chartRef: { kind: OCIRepository, name: <app> }`
  - Keep install/upgrade/values blocks unchanged

**Option B — shared OCIRepository in `kubernetes/flux/meta/repos/`** (when multiple apps share the chart):
- Create/update `kubernetes/flux/meta/repos/<chart>.yaml` with `kind: OCIRepository`
- Rewrite HelmRelease `spec.chartRef: { kind: OCIRepository, name: <chart>, namespace: flux-system }`
- Update `kubernetes/flux/meta/repos/kustomization.yaml` resources list

### Stage 5 — handle the old HelmRepository

```bash
# Is this HelmRepository used by other apps?
rg -l "name: <helm-repo-name>" kubernetes/apps/
```

- **No other users** → delete `kubernetes/flux/meta/repos/<old>.yaml` AND remove it from `kubernetes/flux/meta/repos/kustomization.yaml`
- **Still in use** → leave the file, add a TODO comment noting which apps remain

### Stage 6 — preserve Renovate tracking

Every OCIRepository MUST have:

```yaml
  ref:
    # renovate: datasource=docker depName=<oci-path-without-oci-prefix>
    tag: <version>
```

Missing this comment = Renovate won't track version bumps. Non-negotiable.

### Stage 7 — verify

```bash
# Must succeed
kustomize build kubernetes/apps/<ns>/<app>/app
kustomize build kubernetes/flux/meta/repos
flux build kustomization <app> --path kubernetes/apps/<ns>/<app>/app --dry-run 2>&1 | tail -30

# Verify no stale references
rg "kind: HelmRepository" kubernetes/apps/<ns>/<app>/
rg "sourceRef:" kubernetes/apps/<ns>/<app>/
# Both should be empty
```

If any command errors, STOP — roll back via `git restore` and report.

### Stage 8 — report

```
Migrated: <ns>/<app>
Files changed:
  <list>
Old HelmRepository: <deleted | kept (used by: <apps>)>
Verify: kustomize build + flux build --dry-run PASS
Next: commit + push + watch flux reconcile <app> --context home
```

## Non-negotiable rules

- **NEVER** touch more than one app per invocation — concurrent migrations obscure failure cause
- **NEVER** delete a shared HelmRepository without proving zero remaining users with `rg`
- **NEVER** drop the Renovate comment during migration — loses version tracking
- **NEVER** skip the `kustomize build` verify — silent schema drift from chart version jump is the #1 migration failure mode
- **NEVER** bump chart version during migration — keep the same version. Test the pattern change first; bump separately via Renovate.

## Failure recovery

```bash
# Abort clean: restore files
git restore kubernetes/apps/<ns>/<app>/
git restore kubernetes/flux/meta/repos/
```

Then inspect what went wrong — usually either OCI tag doesn't exist at that version, or the chart renamed from its HelmRepository form to its OCI form (e.g., `descheduler/descheduler` vs `descheduler`).

## When NOT to use

- App is already on `OCIRepository` → no-op
- Chart has no OCI artifact upstream → migration impossible; document with TODO
- Version bump → Renovate handles, not this skill
- Brand-new app → use `new-app` skill, not migration
