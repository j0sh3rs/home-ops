# Improvement Plans

Written 2026-11-24 against commit `8b27891f` by the `improve` skill (standard
effort, advisor run). Each plan is self-contained: an executor with zero
session context should be able to follow it. Update the status column as
plans land.

## Execution order

| # | Plan | Priority | Effort | Risk | Depends on | Status |
|---|------|----------|--------|------|------------|--------|
| 001 | [wyoming-openai reloader annotation](001-wyoming-openai-reloader.md) | P1 | S | LOW | — | DONE (commit `8fdc75f5`, merged to main 2026-11-24) |
| 002 | [reloader CI gate](002-reloader-ci-gate.md) | P1 | S | LOW | 001 | DONE (commit `8da79ef5`, landed on main 2026-11-24; content-identical to reviewed worktree commit `79ac6363`) |
| 003 | [README + dead onedr0p files cleanup](003-readme-and-dead-files-cleanup.md) | P2 | S | LOW | — | DONE (commits `71186f08` + `4ab99085`, on main 2026-11-24; tree-identical to reviewed `5f02c95b`) |
| 004 | [validate-secrets: real plaintext gate](004-validate-secrets-gate.md) | P1 | S | LOW | 003 (allowlist seeding) | DONE (commit `5624ffcd`, landed on main 2026-11-24; R4 tracked-scope seed/gate, 37-line allowlist, gate body verbatim-verified, clean scan rc=0) |
| 005 | [ai-eval CI](005-ai-eval-ci.md) | P2 | S | LOW | — | DONE (commit `3222c047`, landed on main 2026-11-24; workflow verbatim vs plan with sanctioned working-directory fallback, 86/86 tests pass locally in shipped invocation shape) |
| 006 | [talos etcd quorum precheck (investigate-first)](006-talos-quorum-precheck.md) | P2 | S/M | LOW | — (needs cluster access) | DONE (verified live 2026-11-24; precheck+wiring+guard already shipped in `440d960f`, exit-code semantics live-verified, comment corrected on main) |
| 007 | [NetworkPolicy baseline, batch 1](007-networkpolicy-baseline.md) | P3 | M | MED | — (needs cluster access) | TODO |
| 008 | [Talos seal at rest + rotate credentials](008-talos-seal-and-rotate.md) | P1 | M | MED | — (Phase B needs cluster window) | Phase A DONE (commit `25375124b7`, landed on main 2026-11-24; seal/unseal tasks + .sops rule + batch finds, dep-not-precondition and sops-marker fixes verified live; Phase B rotate gated on user go) |


## Dependencies & ordering notes

- **002 must land after 001.** The gate fails while any secret-consuming app
  lacks the reloader annotation; 001 removes the only current offender.
  Executing 002 first ships a red CI.
- **004's allowlist must be seeded after 003 lands** (or with 003's
  deletions present). Plan 003 deletes `.github/tests/{nodes,private,public}.yaml`,
  three files that would otherwise be allowlisted.
- **005, 006, 007 are independent** of everything else. 006 and 007 need
  live cluster access; 005 is pure CI.
- Recommended batch: 001 → 002, then 003 → 004 (a natural pair), then 005
  anytime, then 006 (investigation-first), then 007 per-app in its own
  commits.

## Considered and rejected

Do not re-audit these; they were examined and dismissed on 2026-11-24:

- **Flux EXT webhook has no auth** — by design for a LAN-bound, tunnel-routed
  endpoint (see plan docs; the webhook only triggers reconciles, it takes no
  payload).
- **"Missing reload" in cert-manager, flux-instance receiver,
  talos-backups** — these pick up secrets via env at pod creation / fresh
  pods; a restart is not needed.
- **Velero PVC backup coverage** — `defaultVolumesToFsBackup: true`
  (`kubernetes/apps/velero/app/helmrelease.yaml`, schedule `snapshotOnDelete`
  / `PersistentVolume` include) already covers volumes.
- **`${VAR}` interpolations in manifests** — handled by chart envsubst /
  documented (e.g. crowdsec) — intentional.
- **Renovate config split** (`.github/renovate.json5` extends
  `.renovate/*`) — intentional organization, not drift.
- **MCP header-injection scripts** — audited clean.
- **Legacy HelmRepository apps** — already tracked for removal at
  CLAUDE.md:148-156; pending OCI migration, not a new finding.
- **Wider NetworkPolicy coverage** — plan 007 deliberately stops at batch 1;
  the rest is posture (P3), not risk reduction.

## Not audited (scope boundaries)

Standard-effort audit, hotspot-weighted. The following were **not** audited
and may harbor findings a `deep` pass would surface:

- `macos/` Nix flake internals
- `tools/ai-eval/` internal logic (only its CI absence was audited; the
  advisor could not run its test suite)
- crowdsec / authentik deep configuration
- full GitHub Actions step-by-step logic beyond the workflows named in
  these plans

## Conventions every plan follows

- Conventional-commit messages; one branch per plan
  (`advisor/<NNN>-<slug>`); no push/PR without instruction.
- Verification commands are inline in each plan; expect `yamllint`,
  `yaml.safe_load`, and the plan-specific probe battery.
- Each plan's STOP conditions are hard gates: report back, don't improvise.
