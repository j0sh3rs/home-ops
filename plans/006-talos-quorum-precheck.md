# 006 — talos etcd quorum precheck (investigate-first)

**Status: DONE — verified live 2026-11-24. No implementation needed; comment corrected on main.**

## Verdict

The precheck the plan wanted already exists and is wired. `etcd-quorum-precheck`
(`.taskfiles/talos/Taskfile.yaml:57`) has been a `deps` of both `apply-node` and
`upgrade-node` since `440d960f` (ancestor of this plan's baseline `8b27891f`), and
already carried the empty-PEERS guard and a precise comment. This plan's "Current
state" (no task calls it; no guard; vague comment) was stale against that baseline.

### Live evidence (2026-11-24, client talosctl 1.14.6, cluster 1.14.4)

Topology (`talos/talconfig.yaml`, matches `talosconfig`): 3 CP + 1 worker —
bee-jms-01 `.3`, bee-jms-02 `.6`, bee-jms-03 `.10` (CP); bigboi-jms-01 `.4` (worker).

- `talosctl etcd status` (unscoped, all endpoints): 3 healthy CP members, then
  `error from node 192.168.35.4: … etcd status is only available on control plane
  nodes` → **rc=1 on a healthy cluster**. Proves talosctl aggregates any per-node
  error into a non-zero exit.
- `talosctl --nodes 192.168.35.6,192.168.35.3 etcd status` (the task's exact shape
  for target `.10`): rc=0, 2 healthy members, identical RAFT INDEX / LEADER.
- Claim "exits non-zero if any CP member is unhealthy": **holds for down/unreachable
  members** (error aggregation, proven above — this is the incident scenario).
  **Does not hold for partitioned-but-alive members**: their per-node `etcd status`
  succeeds and shows their own view (lagging RAFT INDEX). That case needs manual
  RAFT INDEX comparison across rows — now stated in the task comment.
- Docs (docs.siderolabs.com, v1.14/v1.15 troubleshooting + etcd-maintenance):
  `talosctl etcd` namespace commands are functional only on control-plane nodes —
  matches the observed worker-node error path.

### Plan errors (why the drift check passed but the plan misread state)

1. "no task calls it" — false: `deps` wiring at apply-node:33-35, upgrade-node:53-55 since `440d960f`.
2. "No empty-PEERS guard" — false: guard at lines 69-72, same commit.
3. Step 1.1 `talosctl cluster nodes` — wrong command on 1.14.x: `talosctl cluster` is
   local docker/QEMU only; remote cluster state = `talosctl config info` + scoped
   `talosctl --nodes <peers> etcd status`.
4. `git diff 8b27891f..HEAD` on the Taskfile is empty, so the executor's drift gate
   would have passed — but the plan's claims were wrong about the baseline itself.

## Actions taken

- Comment fix at `.taskfiles/talos/Taskfile.yaml:65-68` (3 lines added, 1 replaced):
  correct exit-code semantics ("down/unreachable or etcd status request errors,
  live-verified 2026-11-24") + partitioned-but-alive caveat. yamllint rc=0. Committed
  to main.
- Case A (guard + precise comment + wiring): already exists — nothing to implement.
- Case B (output-marker detection): not needed — exit code catches the incident
  scenario (mutation while a peer is down). Partitioned-member nuance is documented,
  not exit-code-detectable.

## Follow-up (optional, not in scope)

If silent partition detection is ever wanted: add a RAFT INDEX spread check (max −
min across member rows, threshold in ticks) to the precheck. Not needed for the
quorum-loss incident this plan protects against.
