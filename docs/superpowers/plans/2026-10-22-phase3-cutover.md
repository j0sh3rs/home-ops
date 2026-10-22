# Phase 3: Consumer Cutover to the Mac Studio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve every local-model consumer from production oMLX on `mac-jms-01`, then retire llama-swap and bigboi.

**Architecture:** nix declares oMLX's per-model settings (role aliases, pins, a 16K `max_tokens` default), and a reconciler daemon applies them. Each consumer gets its own oMLX sub key. Hindsight moves first: it goes directly through `ai-tap` to `mac-inference`, with no Omniroute in between. Omniroute lanes come next, then Home Assistant through its #764 rebuild. Decommissioning comes last.

**Tech Stack:** nix-darwin, oMLX v0.7.2 (admin API), SOPS/age, Flux HelmReleases (app-template), Hindsight 0.10.1, ai-tap, `tools/ai-eval`.

**Spec:** `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md` (Phase 3). The model choices come from `docs/ai-history/mac-studio.md` ("Role → model", soak).

## Global Constraints

- The roles are fixed by the bake-off:

  | Role | Model directory | Alias | Mode |
  |---|---|---|---|
  | Reasoner | `gpt-oss-20b-MXFP4-Q8` | `reasoner` | pinned |
  | Agent | `Qwen3.6-35B-A3B-MLX-4bit` | `agent` | pinned, `enable_thinking: false` |
  | Coder | `Qwen3-Coder-Next-MLX-4bit` | `coder` | on demand, `ttl_seconds: 1800` |

- Every model gets `max_tokens: 16384`. This is the default for requests that send none: 265 of 400 Hindsight requests send none, and 3.3% of soak requests ran to the 32,768 global default.
- The resident set is about 30.6 GB, under oMLX's `--memory-guard-gb 80`.
- Every consumer gets its own sub key, `omlx.sub-keys.<name>`, in `macos/secrets/mac-jms-01.sops.yaml`, mirrored into the consumer's cluster SOPS Secret. The main key never leaves the Mac.
- No plaintext secrets, eval corpus, results or raw prompts in git.
- One node-mutating or consumer-mutating step at a time. Each cutover has a single-line rollback.
- Mac sudo, live Omniroute DB edits and Home Assistant changes are operator steps. The agent gives the command and the operator runs it.
- oMLX does not enforce `response_format` or `tool_choice: required`. Hindsight strips JSON fences itself, so grade with `--lenient-json`.

---

### Task 1: Mac prep — model settings reconciler and consumer keys

**Files:**
- Create: `macos/scripts/omlx-model-settings.sh`
- Create: `macos/scripts/test-omlx-model-settings.sh`
- Modify: `macos/modules/omlx.nix` (add `omlxModelSettings`, `omlx-model-settings` daemon, sub-key names)
- Modify: `macos/secrets/mac-jms-01.sops.yaml` (add `omlx.sub-keys.hindsight`, `omlx.sub-keys.omniroute`)
- Modify: `.github/workflows/macos-nix.yaml` (Unit tests step)
- Modify: `docs/runbooks/mac-studio-operations.md` (new "Model settings" section)

**Interfaces:**
- Produces: the aliases `reasoner`, `agent` and `coder` at `http://mac-inference.ai.svc.cluster.local:8000/v1`, and the sub keys `hindsight` and `omniroute`, which Tasks 3 and 5 copy into cluster Secrets.
- `omlx-model-settings <main-key-file> <settings.json>`: logs in through `POST /admin/api/login`. For each model it sends `PUT /admin/api/models/<dir>/settings` with that entry verbatim, then `POST /admin/api/models/<dir>/load` if `is_pinned`; a 409 (already loading) counts as success. Failures are logged per model. Exits 1 if any model failed. Env overrides: `OMLX_BASE_URL`, `OMLX_LOGIN_ATTEMPTS`, `OMLX_LOGIN_DELAY`.

Notes from the v0.7.2 source:
- `ModelSettingsRequest` is `extra="forbid"`, so the nix attr names must be real fields.
- Pinning only exempts a model from eviction. Pinned models are preloaded at startup, but setting a pin at runtime does not load the model. That is why the script calls `/load`.
- Alias, max_tokens, TTL, thinking and pin are not part of the engine runtime signature. Re-sending them every 10 minutes never reloads a model.

- [x] **Step 1:** Write `test-omlx-model-settings.sh`. It uses a Python stub admin API and covers four cases:
  - the happy path (bodies sent verbatim, only the pinned model loaded, main key not in the output);
  - an unknown model (404 reported by name, later models still applied, non-zero exit);
  - a 409 on load (not a failure);
  - a bad main key (login retried `OMLX_LOGIN_ATTEMPTS` times, no settings sent).
- [x] **Step 2:** Run `bash macos/scripts/test-omlx-model-settings.sh`. Expected: FAIL, because the script does not exist yet.
- [x] **Step 3:** Write `omlx-model-settings.sh`, following `omlx-sub-keys.sh`:
  - JSON bodies piped to curl on stdin;
  - mktemp cookie jar, removed by a trap;
  - each model fails independently.
- [x] **Step 4:** Run the test again, then shellcheck. Expected: `PASS: omlx-model-settings`, and shellcheck clean.
- [x] **Step 5:** Wire it in `omlx.nix`. `omlxModelSettings` holds the table above. Serialize it with `pkgs.writeText … (builtins.toJSON …)`. Add a `launchd.daemons.omlx-model-settings` with `RunAtLoad` and `StartInterval = 600`, running as `_omlx`. Add its log file to the preActivation loop.
- [x] **Step 6:** Generate the two sub keys without printing them:
  `openssl rand -hex 32 | jq -R . | sops set --value-stdin macos/secrets/mac-jms-01.sops.yaml '["omlx"]["sub-keys"]["<name>"]'`
  Then add `"hindsight" "omniroute"` to `omlxSubKeyNames`.
- [x] **Step 7:** Add the test to the CI Unit tests step, and add the runbook section.
- [ ] **Step 8:** Open the PR. "Build darwin closure" must pass, and the closure diff should show the new plist and the settings JSON. Merge, which deploys through the pull loop.
- [ ] **Step 9 (operator, after deploy):**
  1. Check the log: `tail /var/log/home-ops/omlx-model-settings.log` should show "settings applied" for all three models. A 404 means the directory name in nix is wrong; fix it in a follow-up PR.
  2. Delete the dropped models to free disk: `sudo rm -rf /opt/ai/models.noindex/Qwen3.8-27B-MLX-4bit`. Do the same for `gpt-oss-120b-MXFP4-Q8` if it is there.
- [ ] **Step 10 (verify, read-only):**
  - `omlx_stat` model memory on metrics.68cc.io rises to about 31 GB and stays there across a 30-minute idle period. That shows the pins are working.
  - Through `mac-inference` with the hindsight sub key, `/v1/models` lists `reasoner`, `agent` and `coder`.
  - `sub-keys.log` shows `hindsight` and `omniroute` applied.

### Task 2: Hindsight completion caps (cluster PR, ships before the repoint)

**Files:**
- Modify: `kubernetes/apps/ai/hindsight/app/helmrelease.yaml` (env block, beside `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS`)

Retain is already capped at 16000. Consolidation and reflect default to None: they send no `max_tokens`, so they run to the engine default. That is 32K today on llama-swap, and 16K on oMLX after Task 1. Capping them in Hindsight keeps the limit consistent on both engines and makes rollback symmetric.

- [ ] **Step 1:** Add the two caps with a comment:

```yaml
        # Bound runaway reasoning on the ops that send no max_tokens (3.3%
        # of Mac soak requests hit the 32K default). Same budget as retain.
        HINDSIGHT_API_CONSOLIDATION_MAX_COMPLETION_TOKENS: "16000"
        HINDSIGHT_API_REFLECT_MAX_COMPLETION_TOKENS: "16000"
```

- [ ] **Step 2:** Verify with `kustomize build kubernetes/apps/ai/hindsight/app | grep -A1 MAX_COMPLETION`. Expected: three caps.
- [ ] **Step 3:** Commit, open the PR and merge. Then watch Hindsight logs for 30 minutes for `finish_reason=length` and for retries.

### Task 3: Repoint Hindsight to the Mac

**Files:**
- Modify: `kubernetes/apps/ai/ai-tap/app/helmrelease.yaml` (`TAP_ROUTES` hindsight upstream)
- Modify: `kubernetes/apps/ai/hindsight/app/helmrelease.yaml` (drop the `HINDSIGHT_API_LLM_API_KEY: not-needed` env line; update the comments that describe llama-swap)
- Modify: `kubernetes/apps/ai/hindsight/app/secret.sops.yaml` (add `HINDSIGHT_API_LLM_API_KEY`)

**Interfaces:**
- Consumes: the `reasoner` alias and the `hindsight` sub key from Task 1.

- [ ] **Step 1:** Copy the key between the two SOPS files without printing it:

```bash
sops -d --extract '["omlx"]["sub-keys"]["hindsight"]' macos/secrets/mac-jms-01.sops.yaml | jq -R . | sops set --value-stdin kubernetes/apps/ai/hindsight/app/secret.sops.yaml '["stringData"]["HINDSIGHT_API_LLM_API_KEY"]'
```

  The Secret uses `stringData`, and its comment confirms every key reaches both pods through envFrom.
- [ ] **Step 2:** Remove the plain `HINDSIGHT_API_LLM_API_KEY: not-needed` line. An explicit `env` entry beats `envFrom`, so leaving it in would shadow the secret. Keep `HINDSIGHT_API_LLM_MODEL: reasoner`; the alias now resolves on oMLX.
- [ ] **Step 3:** In ai-tap, change the hindsight entry in `TAP_ROUTES` to `hindsight=http://mac-inference.ai.svc.cluster.local:8000`. The tap forwards `Authorization` unchanged.
- [ ] **Step 4:** Update the Hindsight comments: the upstream is now oMLX on the Mac, and the concurrency note about the 5 llama-swap slots is now history. Hindsight already has `reloader.stakater.com/auto`, so the Secret change rolls the pods.
- [ ] **Step 5:** Validate:
  - `kustomize build kubernetes/apps/ai/hindsight/app | kubectl apply --dry-run=client -f -`
  - the same for ai-tap;
  - `task sops:verify`;
  - the sops-leak-detector agent.
- [ ] **Step 6:** Commit with the why and the rollback in the message, then open the PR. Rollback is to revert the `TAP_ROUTES` line; the key is ignored by llama-swap. Merge on the operator's go-ahead.

### Task 4: Hindsight watch window (read-only, 24 h)

- [ ] **Step 1:** Pull the tap captures from the cutover onward (README, "Pull a corpus snapshot"). Keep them in `tools/ai-eval/corpus/`, which is gitignored.
- [ ] **Step 2:** Compare against production llama-swap (`docs/ai-history/mac-studio.md`, "prod gpt-oss-20b"):

  | Signal | Source | Pass |
  |---|---|---|
  | HTTP errors | tap `status` / `error` | ≈ 0 |
  | Empty rate | tap `response`, as in `grade.py` `_empty` | ≤ 0.095 |
  | p95 `latency_ms` | tap | ≤ 180 s, no request over 600 s |
  | `finish_reason == "length"` | tap `response` | < 1% |
  | Mac memory | `omlx_stat` | resident about 31 GB, no guard trips |

- [ ] **Step 3:** Record the aggregate table only (no prompts) in `docs/ai-history/mac-studio.md` under "Phase 3: Hindsight cutover".

### Task 5: Omniroute `mac` lanes

Un-park `docs/superpowers/plans/2026-10-19-omniroute-mac-gateway.md` with these amendments. **Gate: drain plan Task 5 (the Omniroute PV move to bee-03) must be done first.**

- [ ] Override R4: keep the Codex/OpenAI and Claude subscription lanes. Only the local lanes move.
- [ ] R3 ("Studio serves zero models") is obsolete. Point the local provider at `http://mac-inference.ai.svc.cluster.local:8000/v1`, using the `omniroute` sub key from Task 1 and the models `reasoner`, `agent` and `coder`.
- [ ] Every Mac connection gets `maxWaitMs: 120000`.
- [ ] Repoint the atuin and argus combos (`coder-large`, `frontier`) one at a time. Live Omniroute changes are operator steps.

### Task 6: Home Assistant

Rebuild through #764 against the `agent` alias, behind the Omniroute `mac` lane. Gate: the scripted intent set (`tools/ai-eval/ha.py`) passes at GPT-5.5 parity. This is the last consumer.

### Task 7: Decommission

Spec Phase 3 items 4 to 7, plus bigboi drain plan Tasks 6 to 8:

- [ ] Stop the `:8003` bake-off oMLX instance on the Mac.
- [ ] Remove ai-tap and its PVC once the last captured consumer has cut over (see the header of ai-tap's HelmRelease).
- [ ] Remove llama-swap and its PVC, llama-swap-apu, the AMD GPU operator and drm-exporter.
- [ ] Retire bigboi:
  1. Cordon and drain it.
  2. `talosctl reset`.
  3. Remove it from `talconfig.yaml`.
  4. Delete `talos/schematic-dgpu.yaml`.
  5. Retire `openebs-hostpath-fast`.
- [ ] Reset the bee-03 BIOS UMA.
- [ ] Rewrite `kubernetes/apps/ai/CLAUDE.md` and the root `CLAUDE.md` (AI serving, GPU operator, node list).
