# macos/ — nix-darwin for the Mac Studio

Spec: `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`.

- **How it applies:** `modules/pull-loop.nix` runs every 5 minutes and
  `darwin-rebuild switch`es `github:j0sh3rs/home-ops/<main sha>?dir=macos#mac-studio`
  whenever `main` moves. Merging to `main` *is* deploying.
- **Before merge:** `task mac:build-local` (build only) or `task mac:apply-local`
  (switch from your working copy). The next move of `main` re-applies `main`.
- **CI:** `.github/workflows/macos-nix.yaml` builds the closure on a hosted macOS
  runner and posts `nix store diff-closures` on the PR.
- **Rollback:** `git revert` on main (the loop applies it), or on the Mac
  `sudo darwin-rebuild --rollback`. The loop doesn't undo a local rollback
  until main moves again.
- **Secrets:** `secrets/*.sops.yaml`, encrypted to the repo key and the Mac's
  own age key (`/var/lib/sops-nix/key.txt` on the Mac). Edit with
  `sops macos/secrets/mac-studio.sops.yaml`.
- **Health:** textfile metrics under `/var/lib/node-exporter/textfile/`, scraped
  via `kubernetes/apps/ai/mac-inference/`.
- **Homebrew:** `cleanup = "zap"` — only declare packages here; by-hand
  installs are removed on the next apply.
