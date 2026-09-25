# OpenViking history

History moved verbatim from `kubernetes/apps/ai/CLAUDE.md` on 2026-09-25 (#710); current state lives in that file.

## OpenViking retirement (2026-09-25, #701)

- **openviking** — **retired 2026-09-25** (#701): the operator preferred Hindsight after hands-on use. Manifests moved to `archive/openviking/`; data (247 MB RocksDB workspace, `ov.conf`, `master.key`) backed up to `/volume1/backups/openviking/openviking-data-2026-09-25.tgz` (mode 600) before the PVC was deleted. Removed with it: the omniroute `shim` sidecar/Service/ConfigMap and `SHIM_SHARED_SECRET` (the direct-to-CLIProxyAPI vlm path), the Omniroute keys `openviking-embedding`/`openviking-vlm` (revoked), the OpenViking-only models (`qwen3-embed`, `qwen2-vl-2b` on the APU; `jina-reranker-v2` on the dGPU — commented out, fetch entries kept), the Claude Code plugin/marketplace/status line on this machine and HolyClaude, and HolyClaude's `~/.openviking` mount. Full prior history (vlm direct-shim design, timeouts, rerank SSRF finding) lives in git history and `docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md`.
