# GitHub Actions Runner Controller (ARC) Runbook

Self-hosted GitHub Actions runners running in-cluster via **legacy-mode ARC**
(`actions.summerwind.dev` CRDs: `RunnerDeployment` + `HorizontalRunnerAutoscaler`).
Manifests live at `kubernetes/apps/actions-runner-system/`.

## Scope & key constraint

- **`j0sh3rs` is a GitHub User account, not an Organization.** The newer
  `gha-runner-scale-set` chart registers scale sets through GitHub's
  **runner-groups API — an org/enterprise-only feature.** On a personal
  account, that registration call never resolves: the controller hangs
  indefinitely on `deleting runner scale set` / `creating runner scale set`,
  no error, no runner ever registers, jobs queue forever. (Root-caused
  2026-08-21 after ~2 days of a hung controller pod — App JWT auth,
  installation-token exchange, and installation status were all independently
  verified healthy; the hang was structural, not a credentials problem.)
  **Do not switch this back to `gha-runner-scale-set` unless the repo moves to
  an Org/Enterprise.**
- Legacy-mode ARC uses **per-repo registration tokens** instead of runner
  groups, which personal accounts do support. Each target repo needs its own
  `RunnerDeployment`/`HorizontalRunnerAutoscaler` pair + GitHub App
  installation — there is **no native org-wide default** for a User account.
- First (and currently only) runner pool: **`home-ops-runner`** →
  `https://github.com/j0sh3rs/home-ops`.

## Architecture

```
actions-runner-controller (Deployment, actions-runner-system)
  └── watches RunnerDeployment / HorizontalRunnerAutoscaler CRs
        └── home-ops-runner RunnerDeployment
              └── ephemeral runner pods (1 per job, containerMode: kubernetes)
                    scaled 1-3 by HorizontalRunnerAutoscaler
                    (TotalNumberOfQueuedAndInProgressWorkflowRuns metric)
```

- **Chart**: `actions-runner-controller` `0.23.7` via classic `HelmRepository`
  (`https://actions-runner-controller.github.io/actions-runner-controller`) —
  GitHub's official "legacy mode" chart, still maintained, just superseded by
  scale sets for org/enterprise use. **Not published as an OCI artifact**
  (only `gha-runner-scale-set` is), hence `HelmRepository` + `sourceRef`
  instead of this repo's usual `OCIRepository` + `chartRef` — confirmed by a
  `DENIED` token response when Flux tried the OCI path first.
- **Runner image**: `ghcr.io/home-operations/actions-runner` (community image
  bundling kubectl / flux / sops / task etc.), Renovate-tracked.
- **Execution**: `containerMode: kubernetes` — each job step runs in a pod;
  work volume is an ephemeral PVC on `openebs-hostpath-fast` (10Gi, RWO).
- **Auth**: GitHub App, creds in SOPS secret `home-ops-runner-secret` — lives
  in `actions-runner-controller/app/secret.sops.yaml` (co-located with the
  controller, NOT under `runners/home-ops/`). This matters: the controller's
  Deployment references this secret by name for its own auth env vars, so it
  must exist *before or alongside* the controller, not after it — putting it
  in the `runners/` Kustomization (which `dependsOn` the controller
  Kustomization) creates a chicken-and-egg that leaves the controller stuck
  in `CreateContainerConfigError`.
- **Webhook cert**: chart's `certManagerEnabled: true` (default) — issued by
  the cluster's existing cert-manager, no extra setup needed.
- **RBAC**: runner SA `home-ops-runner` is bound to **`cluster-admin`** and has
  a Talos **`os:admin`** ServiceAccount (secret mounted at
  `/var/run/secrets/talos.dev`). This lets home-ops CI reconcile Flux / apply
  manifests / run `talosctl`.
  > ⚠️ **Blast radius**: any workflow on this runner pool inherits
  > cluster-admin + Talos os:admin. Install the GitHub App ONLY on trusted
  > repos. For repos that don't deploy, use a scoped Role instead of
  > cluster-admin (see "Add a repo").

## One-time setup: GitHub App (operator, browser)

1. **Create** at GitHub → Settings → Developer settings → **GitHub Apps** →
   New. Name e.g. `j0sh3rs-arc`. Homepage URL anything. **Uncheck** Webhook
   "Active". Repository permissions:
   - **Administration**: Read & write
   - **Actions**: Read & write
   - **Metadata**: Read-only
   - **Checks**: Read & write
   Create the app, then **Generate a private key** (downloads a `.pem`).
2. **Install** the app: app settings → Install App → install on the
   `home-ops` repo (Only select repositories). Confirm it isn't suspended.
3. **Collect the three values**:
   - **App ID** — on the app's General page.
   - **Installation ID** — the trailing number in the install URL
     `https://github.com/settings/installations/<INSTALL_ID>` (this endpoint
     requires the App's own JWT to query via API — easiest to just read it
     off the install URL in the browser).
   - **Private key** — the downloaded `.pem` contents.

## Populate the SOPS secret

The repo ships an **encrypted placeholder** at
`.../actions-runner-controller/app/secret.sops.yaml`. Replace with real values:

```bash
F=kubernetes/apps/actions-runner-system/actions-runner-controller/app/secret.sops.yaml
task sops:decrypt-file file=$F      # opens decrypted; or sops:edit
# set github_app_id, github_app_installation_id, github_app_private_key (full PEM)
task sops:encrypt-file file=$F
task sops:verify                    # MUST show all encrypted
```

(Or use the `sops-edit-then-encrypt` skill / `task sops:edit file=$F` for an
in-place edit that re-encrypts on save.)

## Deploy

Flux auto-discovers the namespace (no `apps.yaml` edit). After merge to `main`:

```bash
flux reconcile kustomization cluster-apps --with-source
flux get ks -A | grep actions-runner
kubectl -n actions-runner-system get pods            # controller Running
kubectl -n actions-runner-system get runnerdeployment,horizontalrunnerautoscaler
kubectl -n actions-runner-system get runners          # actual runner pods registering
```

## Use the runner in a workflow

Set `runs-on` to the `RunnerDeployment` name:

```yaml
jobs:
  build:
    runs-on: home-ops-runner
```

> Existing `home-ops` workflows still target `ubuntu-latest`. Migrating them to
> `home-ops-runner` is a deliberate per-job decision (some jobs may want
> GitHub-hosted egress/clean env) — not flipped wholesale.

## Add another repo

No native default for a User account — enumerate per repo:

1. Install the same GitHub App on the new repo (App settings → Install App).
2. Copy the runner dir:
   `cp -r runners/home-ops runners/<repo>` (under
   `kubernetes/apps/actions-runner-system/actions-runner-controller/`).
3. In the copy, change in **all** files: `RunnerDeployment`/
   `HorizontalRunnerAutoscaler` name `home-ops-runner` → `<repo>-runner`,
   `repository:` → the new repo, `repositoryNames:` in the HRA, and the
   ServiceAccount/RBAC names.
4. **RBAC**: if the repo does NOT deploy to the cluster, replace the
   `cluster-admin` ClusterRoleBinding + Talos SA in `rbac.yaml` with a scoped
   Role (or drop RBAC entirely) — don't hand every repo cluster-admin.
5. Add `- ./<repo>` to `runners/kustomization.yaml`.
6. The GitHub App creds are shared (one App, one installation-token flow) —
   only add a new secret if you want per-repo credential isolation.

## Troubleshooting

```bash
# Controller logs
kubectl -n actions-runner-system logs deploy/actions-runner-controller
# RunnerDeployment / HRA / Runner status
kubectl -n actions-runner-system get runnerdeployment,horizontalrunnerautoscaler,runners
kubectl -n actions-runner-system describe runnerdeployment home-ops-runner
# A stuck job: runner pod events
kubectl -n actions-runner-system get pods
kubectl -n actions-runner-system describe pod <runner-pod>
# HelmRelease state
flux -n actions-runner-system get hr
```

Common issues:
- **Controller hangs indefinitely with no error, ever** (not a crash, not a
  restart loop — just stalls mid-reconcile): if you're back on
  `gha-runner-scale-set`, this is the org/enterprise-only runner-groups
  limitation above, not a fixable config issue. If you're on legacy-mode ARC
  and see this, check `certManagerEnabled` actually issued a serving cert
  (`kubectl -n actions-runner-system get certificate`) — the webhook server
  can stall startup if cert-manager didn't complete.
- **`CreateContainerConfigError` on the controller pod**: `authSecret.name`
  doesn't match an existing secret, or the secret's keys aren't exactly
  `github_app_id` / `github_app_installation_id` / `github_app_private_key`
  (case-sensitive, chart looks them up literally).
  Also check ordering: the secret lives in `app/`, not `runners/`, precisely
  to avoid the controller starting before its own auth secret exists.
- **App auth itself in doubt**: verify independently of the controller —
  build a JWT from the App's private key and hit `GET /app` (should 200),
  then `POST /app/installations/<id>/access_tokens` (should 201). If those
  fail, it's genuinely a credentials/permissions/suspension problem in the
  GitHub App; if they succeed, look elsewhere.
- **Runner pods Pending on PVC**: `openebs-hostpath-fast` is node-local
  (WaitForFirstConsumer) — fine, binds on schedule. Pending elsewhere = quota.
- **Job can't reach cluster**: confirm the runner pod mounted
  `/var/run/secrets/talos.dev` and the SA has the expected binding.

## References

- Manifests: `kubernetes/apps/actions-runner-system/`
- Chart: <https://github.com/actions/actions-runner-controller/tree/master/charts/actions-runner-controller>
- Legacy-mode docs: <https://github.com/actions/actions-runner-controller/blob/master/docs/quickstart.md>
- Why legacy mode, not scale sets, on this repo: <https://github.com/actions/actions-runner-controller/discussions/2775>
