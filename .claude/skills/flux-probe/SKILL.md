---
name: flux-probe
description: Triage failing Flux Kustomizations and HelmReleases in a namespace. Prints status, describe, failing-pod logs, and maps back to the repo YAML file. Read-only — no cluster mutations. Invoke with /flux-probe <namespace> or /flux-probe <namespace>/<resource-name>.
---

# flux-probe (home-ops)

Triage a failing Flux resource without the usual 5-command juggling. Read-only. All commands use `--context home` per repo convention.

## Usage

- `/flux-probe` — list failing Kustomizations + HelmReleases across all namespaces
- `/flux-probe <namespace>` — focus on one namespace
- `/flux-probe <namespace>/<name>` — deep dive on one resource

## Workflow

### Stage 1 — enumerate failures

```bash
rtk flux get ks -A --context home | grep -vE "True.*Applied|NAME"
rtk flux get hr -A --context home | grep -vE "True.*Helm (install|upgrade) succeeded|NAME"
```

If arg provided, filter to that namespace.

### Stage 2 — identify resource kind

For each failing entry, determine whether it's a Kustomization or HelmRelease. Then:

**Kustomization**:
```bash
rtk kubectl -n <ns> describe kustomization.kustomize.toolkit.fluxcd.io/<name> --context home
rtk flux logs --kind=Kustomization --namespace=<ns> --name=<name> --context home
```

**HelmRelease**:
```bash
rtk kubectl -n <ns> describe helmrelease/<name> --context home
rtk flux logs --kind=HelmRelease --namespace=<ns> --name=<name> --context home
```

### Stage 3 — underlying pod status (for HelmRelease)

```bash
rtk kubectl -n <ns> get pods -l app.kubernetes.io/name=<name> --context home
rtk kubectl -n <ns> describe pod -l app.kubernetes.io/name=<name> --context home | head -80
rtk kubectl -n <ns> logs -l app.kubernetes.io/name=<name> --tail=50 --context home
rtk kubectl -n <ns> get events --sort-by='.metadata.creationTimestamp' --context home | tail -15
```

### Stage 4 — map back to repo

Grep repo for the resource to identify source file:

```bash
rg "name: <name>" kubernetes/apps/<ns> --glob "*.yaml" -l
```

### Stage 5 — render triage

Output structure:
```
Resource: <ns>/<name> (<kind>)
State: <Ready=False reason>
Source: kubernetes/apps/<ns>/<name>/app/helmrelease.yaml:<line>

Root cause (best guess):
<1-2 sentences>

Fix suggestion:
<concrete action>

Next commands:
<2-3 targeted commands the user should run>
```

## Invariants

- NEVER run `kubectl apply`, `flux reconcile --force`, `kubectl delete`, or any cluster-mutating command from this skill
- NEVER decrypt SOPS files
- Always prefix cluster commands with `rtk` for token savings
- Always pass `--context home` explicitly
- If output exceeds 500 lines, truncate + summarize — user can rerun specific stage manually

## Common failure modes + root causes

- **HelmRelease `ProgressingWithRetry` → `InstallFailed` "timeout waiting for Deployment"**: initial install, underlying pod not Ready. Usually probe config wrong, image pull, or PVC pending. Stage 3 reveals.
- **HelmRelease `values don't meet the specifications of the schema`**: bjw-s app-template v4 schema drift. Field moved (e.g., `serviceAccountName` → `controllers.<n>.serviceAccount.name`). Stage 2 shows schema path.
- **Kustomization `build failed: failed to decrypt`**: SOPS regex mismatch or unencrypted `*.sops.yaml` committed. Check `task sops:verify`.
- **HTTPRoute hostname has no cert**: cert-manager reconcile lagging. Check `kubectl get certificate -A`.
- **Pod `ImagePullBackOff`**: Renovate tag drift, or registry auth. Stage 3 + `kubectl describe pod`.
