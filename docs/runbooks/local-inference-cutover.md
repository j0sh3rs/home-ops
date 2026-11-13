# Local inference cutover: Hindsight, Home Assistant conversation, voice

**Status:** prepared 2026-11-13, not yet applied to the cluster. Evidence and decisions:
`docs/research/2026-11-13-omlx-splash-model-evaluation/` (start with `fast-lane-and-voice.md`).

## What the Mac already provides (applied on the Mac, 2026-11-13)

Pinned resident set on the oMLX instance behind `mac-inference.ai.svc.cluster.local:8000`
(about 50 GB planned against a 70 GiB memory ceiling):

| Alias | Model | Used for |
|---|---|---|
| `local-coding`, `local-coding:long` | Qwen3.8-27B oQ4e on Splash, 128K | Coding agents (unchanged consumers) |
| `reasoner` | gpt-oss-20b (MXFP4-Q8) | Hindsight |
| `local-ha` | gemma-4-E4B (8-bit) | Home Assistant conversation |
| `local-stt` | Whisper large-v3-turbo (fp16) | Speech-to-text |
| `local-tts` | Kokoro-82M, voice `af_heart` | Text-to-speech |

Three per-consumer oMLX sub keys exist: `hindsight`, `home-assistant`, `voice-bridge`. Sub keys can run
inference but not administer oMLX. Their values are in a mode-0600 file on the Mac
(`~/.omlx/sub-keys-handoff.json`); the `hindsight` and `voice-bridge` keys are already SOPS-encrypted in this
change. The `home-assistant` key is for you to paste into Home Assistant. Never commit it.

## 0. Prerequisite: one canonical oMLX instance (operator decision)

Two oMLX instances exist on `mac-jms-01`, and the running one is not the nix-managed service:

- The instance serving port 8000 today is the **user-run oMLX app** (`~/.omlx`, launched at login). The aliases,
  pins, 70 GiB ceiling and the three sub keys above were applied there.
- The **nix-managed launchd service** (`macos/modules/omlx.nix`, `_omlx` user, `/opt/ai/omlx`) fails every ~30 s
  with `Address already in use` because the app holds the port, and its reconcilers (`omlx-sub-keys`,
  `omlx-model-settings`) log `admin login failed (server down or main key mismatch)`. They run on the Mac, so they
  are exempt from oMLX's wrong-key lockout (oMLX does not count loopback or same-address peers) and are not the
  source of the earlier `429 Too many wrong API keys` responses.

The 429s came from the in-cluster **Gatus** probe `mac-inference-models` (`/v1/models` every minute with
`MAC_INFERENCE_GATUS_KEY`). That key belonged to the nix-managed instance and was unknown to the app instance, so
every probe was a wrong key: 626 rejections in one day, all with fingerprint `6b910a23`, which matches the
SHA-256 prefix of the Gatus key. oMLX locks out per source address and Cilium masquerades pods to the node IP, so
**every consumer on the same node was locked out too** (a locked-out source gets 429 before its key is even
checked). That would have hit the Hindsight, tap and bridge traffic on that node after this PR. It was mitigated
on the Mac on 2026-11-13 by registering the existing Gatus key as an app-instance sub key named `gatus`; the
cluster secret is unchanged.

Decide which instance is canonical before merging. If the app stays canonical, disable the nix service and its
reconcilers (otherwise they keep failing and could win the port after a restart, serving different models and
keys). If the nix service becomes canonical, quit the app and re-declare the aliases, pins, ceiling and sub keys in
the nix and SOPS config so the Hindsight and bridge keys in this PR match the ones the reconciler creates. The
keys in this PR exist only in the app instance's settings.

## 1. Hindsight cutover (PR: Hindsight + ai-tap)

Changes: the ai-tap `hindsight` route now points at `mac-inference`; Hindsight uses provider `openai`, base URL
`http://ai-tap.ai.svc.cluster.local:8080/hindsight/v1`, model `reasoner`, and the `hindsight` sub key. This
replaces the temporary Codex OAuth route (`openai-codex`, `gpt-6.1-luna`).

Before merging:

- [ ] On the Mac, `curl` the Mac from a pod: `/v1/models` with the sub key lists `reasoner`.
- [ ] Mac idle check: no coding session mid-prefill you would interrupt (the Hindsight backlog will run
      background retain and consolidation at up to 4 concurrent requests).
- [ ] `kustomize build kubernetes/apps/ai/hindsight/app` and `.../ai-tap/app` succeed (done in the PR).

Merge, then watch for 24 hours (pull tap captures as in `tools/ai-eval/README.md`):

| Signal | Source | Pass |
|---|---|---|
| HTTP errors | tap `status` / `error` | about 0 |
| Empty rate | tap `response`, as in `grade.py` `_empty` | <= 0.095 |
| p95 latency | tap `latency_ms` | <= 180 s, nothing over 600 s |
| `finish_reason == "length"` | tap `response` | < 1% |
| Mac memory and swap | `omlx_stat`, `vm_stat` | resident about 50 GB, no new swapouts |

Caveats: oMLX does not enforce `response_format`, so `HINDSIGHT_API_LLM_STRICT_SCHEMA_RETAIN` only requests it
(replayed answers were schema-valid on 98.9% of requests). In the evaluation, about 1 in 100 requests hit the
length cap. Rollback: revert the PR (the Codex PVC and mount were kept for this reason) or revert only the three
`HINDSIGHT_API_LLM_*` lines and the tap route.

## 2. Home Assistant: remove the shell tool first (operator step)

Every model tested calls `bash` when asked to run a shell command, so do this before any local model is used
as a conversation agent. It is the open follow-up in `docs/runbooks/home-assistant-mcp.md`.

1. In HA, open the `extended_openai_conversation` conversation subentry (see the entry and subentry IDs in
   `home-assistant-mcp.md`) and delete the `bash` and `load_skill` functions from its `functions` list, leaving
   `execute_services` and `get_attributes` (and any you added on purpose).
2. Reload the integration and confirm `what is in /config` no longer produces a shell call.

## 3. Home Assistant: local conversation agent and voice (trial)

Keep the current Assist pipeline untouched as the fallback. Create a second pipeline for the trial.

1. **Wyoming bridge:** after merging the PR, Flux deploys `wyoming-openai` in the `ai` namespace
   (`wyoming-openai.ai.svc.cluster.local:10300`). In HA add a Wyoming integration at that host and port; it
   exposes the `local-stt` Whisper and `local-tts` Kokoro services.
2. **Conversation agent:** add a second `extended_openai_conversation` entry. Base URL
   `http://mac-inference.ai.svc.cluster.local:8000/v1`, model `local-ha`, API key = the `home-assistant` sub key
   (never the main key), with `bash` and `load_skill` removed from its functions. Use the classic
   `execute_services` and `get_attributes` function definitions and keep the instruction "act immediately; do not
   ask for confirmation" in the prompt (a confirmation question fails every control request).
3. **Pipeline:** create "Local" with conversation = the new agent, STT = Whisper (bridge), TTS = Kokoro (bridge).
   Test from the Assist UI and one satellite before making it the preferred pipeline.
4. **Fallback:** the existing pipeline, `faster-whisper` and `piper` remain deployed. The Mac down means local
   voice is down; fall back by selecting the old pipeline (the Mac also hosts the LLM today).

Measured on the Mac with synthetic input (see the research doc for limits): E4B passes 22 of 23 unique non-shell
cases with a first token of about 0.4 to 0.5 s warm; Whisper about 0.13 s median, 0.26 s under a long prefill;
Kokoro about 0.06 s, 0.2 s under a long prefill. Real satellite audio and real entity lists are untested, so judge
the trial on real use before cutting over.

## 4. Mac-side operations

- Resident models are pinned (`reasoner`, `local-ha`, `local-stt`, `local-tts`, coding). Other models
  (gemma-4-26B, parakeet) unload after 900 s idle.
- To stay out of swap: run evaluations one candidate at a time and avoid loading extra large models next to the
  pinned set; check `vm_stat` swapouts and `memory_pressure` after any experiment.
- Do not manually unload the Q8 Splash model: one manual unload stalled for about 4 minutes and the server
  restarted (cause unknown).
- Rotate a sub key by creating a new one in oMLX, updating the consumer's SOPS secret, then deleting the old one.
