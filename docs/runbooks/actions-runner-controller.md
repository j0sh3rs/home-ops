# GitHub Actions Runner Controller (ARC) Runbook

Self-hosted GitHub Actions runners running in-cluster via the official
**Actions Runner Controller** (`gha-runner-scale-set`). Manifests live at
`kubernetes/apps/actions-runner-system/`.

## Scope & key constraint

- **`j0sh3rs` is a GitHub User account, not an Organization.** Runner scale
  sets register at **repo / org / enterprise** level only. A personal user
  account supports **repo-level only** — there is **no native "default for all
  repos."** Each target repo needs its own scale set + GitHub App installation.
- True org-wide default would require creating a GitHub Organization and
  transferring repos in.
- First (and currently only) scale set: **`home-ops`** →
  `https://github.com/j0sh3rs/home-ops`.

## Architecture

```
gha-runner-scale-set-controller (Deployment, actions-runner-system)
  └── watches AutoScalingRunnerSet CRs
        └── home-ops scale set (HelmRelease home-ops-runner)
              ├── listener pod (long-lived, polls GitHub)
              └── ephemeral runner pods (1 per job, containerMode: kubernetes)
```

- **Chart**: `oci://ghcr.io/actions/.../gha-runner-scale-set{,-controller}`
  `0.14.2` (controller + scale set version-coupled — bump in lockstep).
- **Runner image**: `ghcr.io/home-operations/actions-runner` (community image
  bundling kubectl / flux / sops / task etc.), pinned by digest, Renovate-tracked.
- **Execution**: `containerMode: kubernetes` — each job step runs in a pod;
  work volume is an ephemeral PVC on `openebs-hostpath-fast` (10Gi, RWO).
- **Auth**: GitHub App, creds in SOPS secret `home-ops-runner-secret`.
- **RBAC**: runner SA `home-ops-runner` is bound to **`cluster-admin`** and has
  a Talos **`os:admin`** ServiceAccount (secret mounted at
  `/var/run/secrets/talos.dev`). This lets home-ops CI reconcile Flux / apply
  manifests / run `talosctl`.
  > ⚠️ **Blast radius**: any workflow on this scale set inherits cluster-admin +
  > Talos os:admin. Install the GitHub App ONLY on trusted repos. For repos that
  > don't deploy, use a scoped Role instead of cluster-admin (see "Add a repo").

## One-time setup: GitHub App (operator, browser)

1. **Create** at GitHub → Settings → Developer settings → **GitHub Apps** →
   New. Name e.g. `j0sh3rs-arc`. Homepage URL anything. **Uncheck** Webhook
   "Active". Repository permissions:
   - **Administration**: Read & write
   - **Actions**: Read & write
   - **Metadata**: Read-only
   - **Checks**: Read & write
   Create the app, then **Generate a private key** (downloads a `.pem`).
2. **Install** the app: app settings → Install App → install on the `home-ops`
   repo (Only select repositories).
3. **Collect the three values**:
   - **App ID** — on the app's General page.
   - **Installation ID** — the trailing number in the install URL
     `https://github.com/settings/installations/<INSTALL_ID>`, or:
     `gh api /users/j0sh3rs/installation --jq '.id'` (once installed).
   - **Private key** — the downloaded `.pem` contents.

## Populate the SOPS secret

The repo ships an **encrypted placeholder** at
`.../runners/home-ops/secret.sops.yaml`. Replace with real values:

```bash
F=kubernetes/apps/actions-runner-system/actions-runner-controller/runners/home-ops/secret.sops.yaml
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
kubectl -n actions-runner-system get pods           # controller + listener Running
kubectl -n actions-runner-system get autoscalingrunnerset
```

## Use the runner in a workflow

Set `runs-on` to the scale set name (= HelmRelease `metadata.name`):

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
3. In the copy, change in **all** files: scale-set name `home-ops-runner` →
   `<repo>-runner`, `githubConfigUrl` → the new repo, and the secret name.
   **Re-encrypt the new `secret.sops.yaml`** with that repo's install ID.
4. **RBAC**: if the repo does NOT deploy to the cluster, replace the
   `cluster-admin` ClusterRoleBinding + Talos SA in `rbac.yaml` with a scoped
   Role (or drop RBAC entirely) — don't hand every repo cluster-admin.
5. Add `- ./<repo>` to `runners/kustomization.yaml`.

## Troubleshooting

```bash
# Controller / listener logs
kubectl -n actions-runner-system logs deploy/actions-runner-controller
kubectl -n actions-runner-system logs -l app.kubernetes.io/component=runner-scale-set-listener
# Scale set status (registered? failures?)
kubectl -n actions-runner-system describe autoscalingrunnerset home-ops-runner
# A stuck job: ephemeral runner pod events
kubectl -n actions-runner-system get pods
kubectl -n actions-runner-system describe pod <runner-pod>
# HelmRelease state
flux -n actions-runner-system get hr
```

Common issues:
- **Listener CrashLoop / 401**: bad/expired GitHub App creds or app not
  installed on the repo. Re-check the three secret values + installation.
- **Runner pods Pending on PVC**: `openebs-hostpath-fast` is node-local
  (WaitForFirstConsumer) — fine, binds on schedule. Pending elsewhere = quota.
- **Job can't reach cluster**: confirm the runner pod mounted
  `/var/run/secrets/talos.dev` and the SA has the expected binding.

## References

- Manifests: `kubernetes/apps/actions-runner-system/`
- Modeled on `onedr0p/home-ops/kubernetes/apps/actions-runner-system` (adapted:
  SOPS instead of external-secrets, `openebs-hostpath-fast`, `common`
  component, `kubernetes-schemas.pages.dev` headers).
- Upstream: <https://github.com/actions/actions-runner-controller>
