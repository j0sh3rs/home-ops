# 008 — Talos cluster configs: encrypt at rest + rotate credentials

**Status: Phase A LANDED on main `25375124b7` (2026-11-24). Phase B (rotate) gated on a cluster window + user go.**

## Why

Two distinct risks, two distinct fixes:

1. **Stale credentials** — the cluster's CA, node tokens, and admin client cert have lived
   in local plaintext files since October 2026. If any copy leaked (backup, sync, disk
   image), the credentials remain valid indefinitely. **Rotate** generates a new
   CA/tokens, invalidating every old copy.
2. **Plaintext at rest** — the five cluster config files sit on the Studio in plaintext
   (already 600, already gitignored, never tracked). **Encrypt at rest** with SOPS/age so
   a stolen disk or backup yields ciphertext.

Threat-model honesty: `age.key` lives on the same machine. Encryption protects against
at-rest disclosure (theft, backup, forensic), not a local user who owns the machine.
Rotation is the stronger control; encryption is defense-in-depth.

## Current state (verified 2026-11-24)

- All tracked k8s secrets are already SOPS-encrypted (`*.sops.yaml`, 60+ files).
  Nothing tracked needs encrypting. The 004 allowlist covers tracked non-secret matches.
- The five plaintext files are **local-only, gitignored, never tracked**:
  `talos/clusterconfig/kubernetes-bee-jms-0{1,2,3}.yaml`,
  `talos/clusterconfig/kubernetes-bigboi-jms-01.yaml` (node machine configs embedding
  CA + node tokens), and `talos/clusterconfig/talosconfig` (admin client cert).
  Perms 600. Cluster: 1 cluster, 3 CP (`.3/.6/.10`) + 1 worker (`.4`), 192.168.35.x.
- `talos/talsecret.sops.yaml` is tracked and already encrypted — the CA/token source.
- `.sops.yaml` has a rule for `talos/.*\.sops\.ya?ml` but **none** for `talos/clusterconfig/`
  (files have no `.sops.yaml` suffix), so `sops --encrypt` on them fails today.
- `.taskfiles/sops/Taskfile.yaml` batch finds (`encrypt` :11, `decrypt` :43, `verify` :138,
  `rotate` :177, `updatekeys` :199) only cover `kubernetes/ bootstrap/ archive/` — the two
  tracked `talos/` sops files are invisible to batch ops.
- `talhelper gencommand apply` consumes **plaintext** `kubernetes-<node>.yaml` from
  `clusterconfig/` at apply time; `talhelper genconfig` writes them plaintext.
  `TALOSCONFIG` (`.mise.toml:16`, root `Taskfile.yaml` env) points at
  `talos/clusterconfig/talosconfig`; `talosctl` reads it directly.
- Taskfile v3 execution order is **deps (listed order) → preconditions → cmds** (verified
  empirically with file-marker tasks). So unseal must be the **first dep**, not a
  precondition — as a precondition it would run after the 006 quorum precheck, which
  reads the talosconfig via talosctl.
- The 006 `etcd-quorum-precheck` is already a dep of `apply-node`/`upgrade-node`
  (`440d960f`, comment corrected in `967d6a27`) — Phase B CP applies get quorum gating
  for free.
- `.private/` is gitignored but absent on disk.

## Phase A — seal/unseal mechanics (no cluster window)

1. `.sops.yaml`: add creation rule
   ```yaml
   - path_regex: talos/clusterconfig/.*
     mac_only_encrypted: true
     age: "age1qwwzsz6z2mmu6hpmjt2he7nepmnhutmhehvkva7l5zy5xzf08d5s5n4d6n"
   ```
   (whole-file encryption, no `encrypted_regex`).
2. `.taskfiles/talos/Taskfile.yaml`: two new tasks.
   - `seal`: for each of the 5 clusterconfig files, skip if `grep -q '^sops:'`, else
     `sops --encrypt --in-place <file>`. `dir: '{{.TALOS_DIR}}/clusterconfig'`.
     Preconditions: `.sops.yaml`, `SOPS_AGE_KEY_FILE`, `which sops`.
   - `unseal`: for each file, skip if not sealed, else `sops --decrypt <file> > tmp &&
     mv tmp <file> && chmod 600 <file>` (NEVER `--in-place` decrypt on a file the
     toolchain reads). Fail loud (exit 1) if any expected file is missing.
   Keep the existing `desc`/comment style of this file.
3. `generate-config`: add `postcmd: task talos:seal` so freshly generated plaintext
   configs are sealed immediately.
4. `apply-node` and `upgrade-node`: add **first precondition** `sh: task talos:unseal`
   (before the existing `talosctl` preconditions). The `etcd-quorum-precheck` dep is
   unchanged (deps run after preconditions → plaintext available).
5. `.taskfiles/sops/Taskfile.yaml`: add `talos/` to the five batch finds
   (`find kubernetes/ bootstrap/ archive/ talos/ ...`).
6. Create `.private/` (gitignored) — used by Phase B backups.

### Phase A verification (offline)

- `sops:verify` passes (now covers talos/ sops files).
- Round-trip: on a scratch copy of one clusterconfig file, `sops --encrypt` → `sops -d`
  → byte-identical. Then seal/unseal the real five files once each; after unseal,
  `talosctl config info` (TALOSCONFIG env) still parses.
- `task talos:seal` idempotent (second run: all skipped).
- yamllint clean on both touched Taskfiles (lint config `.github/linters/.yamllint.yaml`).
- Dep ordering: `task talos:apply-node IP=<worker>` must unseal before the quorum
  precheck (dep order; do NOT let it apply).

### Phase A execution notes (2026-11-24, commit `25375124b7`)

- All offline verification ran clean: `sops:verify`, seal→unseal→`talosctl config info`
  (4 nodes, admin role, cert valid to 2027-10-23), idempotent re-seal, yamllint.
- **Fix 1 — dep, not precondition.** Taskfile v3 runs deps before preconditions
  (empirically verified). The draft design made unseal a precondition of
  `apply-node`/`upgrade-node`; that would have run after the 006 quorum precheck,
  whose `talosctl` reads the still-sealed talosconfig. Shipped as the first dep.
- **Fix 2 — skip marker.** The draft skip check `grep -q '^sops:'` works for
  `.yaml` inputs (sops emits a `sops:` key) but fails for extensionless files:
  sops 3.13.3 wraps `talosconfig` as JSON `{"data": "ENC[AES256_GCM,..."}`, which has
  no `sops:` line — talosconfig would never be re-sealed/unsealed. Shipped check:
  `grep -q 'ENC\[AES256_GCM'` (universal marker, both formats).
- Round-trip detail: `talosconfig` is byte-identical after unseal; the four
  `kubernetes-*.yaml` files come back semantically identical but re-indented to
  4 spaces (sops re-serializes YAML). Cosmetic only — the files are gitignored and
  consumed by YAML parsers.

## Phase B — rotate (cluster window, user go required)

1. **Backup**: `cp -f talos/talsecret.sops.yaml .private/talsecret.sops.yaml.bak-<ts>`;
   copy `talos/clusterconfig/` → `.private/backup-<ts>/`.
2. `talhelper gensecret | sops --filename-override talos/talsecret.sops.yaml --encrypt /dev/stdin > talos/talsecret.sops.yaml`
   (new CA/tokens; repo copy updated).
3. `talhelper genconfig` (new node configs + talosconfig, plaintext in clusterconfig/).
4. **Apply order** — CP nodes first, worker last:
   - `task talos:apply-node IP=192.168.35.3` → `...35.6` → `...35.10`
     (each unseals + runs the 006 quorum precheck on the other two CP peers before
     mutating; a failing peer aborts the run).
   - Then `task talos:apply-node IP=192.168.35.4` (worker; precheck is CP-only, no gate).
5. `talhelper gencommand kubeconfig --extra-flags="{{.ROOT_DIR}} --force" | bash`
   (new admin kubeconfig at repo root).
6. **Verify**: `talosctl etcd status` (3 healthy members, single leader, equal raft
   indices), `kubectl get nodes` (4 Ready), `flux reconcile` clean.
7. `task talos:seal` (re-encrypt the rotated configs). Commit `talsecret.sops.yaml`.
8. **Recovery on mid-rotation failure**: stop applying; re-apply the backup configs
   (old CA) to the already-rotated nodes from `.private/backup-<ts>/`, then resume
   later. If quorum is already lost, Talos nodes with valid old configs can re-join
   from etcd snapshots — escalate to user, do not improvise.

## Stop conditions

- `talsecret.sops.yaml` missing or undecryptable → STOP.
- Cluster unreachable (`talosctl config info` fails) → STOP (Phase B).
- Any CP apply-node precheck failure during Phase B → STOP, recover per step 8.
- `sops --encrypt` fails on a clusterconfig file (creation rule mismatch) → fix rule,
  do not hand-roll `--age` flags.

## Out of scope

- k8s in-cluster certificate rotation (kubelet/SA serving certs) — Talos rotates these
  on config apply as part of Phase B; no separate task.
- Rotating the age keypair itself (`sops:rotate` across all 60+ files) — separate
  decision; Phase A's find fix makes it viable later.
- `kubeconfig` at repo root: regenerated in Phase B step 5; stays plaintext 600
  (kubectl reads it directly; sealing it would break the `KUBECONFIG` env flow).

## Commit style

- Phase A: `talos: seal/unseal cluster configs at rest` (or split mechanics/finds).
- Phase B: `talos: rotate cluster CA and node credentials`.
