---
name: sops-edit-then-encrypt
description: Safely edit SOPS-encrypted YAML files in home-ops. Decrypts, applies requested changes, re-encrypts, and verifies before returning control. Prevents the common failure mode of committing a plaintext secret because re-encryption was forgotten. Use whenever editing any file matching *.sops.yaml.
---

# sops-edit-then-encrypt (home-ops)

SOPS edit workflow with enforced round-trip. Prevents plaintext commits.

## When to invoke

- User asks to change a value inside a `*.sops.yaml` file
- Any edit to files matching the pattern `kubernetes/**/*.sops.yaml`, `bootstrap/**/*.sops.yaml`, `talos/**/*.sops.yaml`

## Workflow

### 1. Pre-flight check

```bash
task sops:verify 2>&1 | rg -i "not encrypted|failed" && echo "Unencrypted files exist — abort" || echo "All encrypted OK"
```

If any file is plaintext before you start, stop and ask the user what they want to do with those. Do not proceed until the working tree is clean.

### 2. Decrypt target file

```bash
task sops:decrypt-file file=<path-to-secret.sops.yaml>
```

Output must include `✅ Decrypted` or `ℹ️  not encrypted`. If already plaintext, note it and proceed (rare — usually means a prior edit was interrupted).

### 3. Apply edits

Use `Edit` or `Write` to make requested changes. Keep edits minimal and atomic.

### 4. Re-encrypt immediately

```bash
task sops:encrypt-file file=<path-to-secret.sops.yaml>
```

Output must include `✅ Encrypted`.

### 5. Verify encryption landed

```bash
rg -c "ENC\[AES256_GCM" <path-to-secret.sops.yaml>
```

Must return > 0. If it returns 0 or errors, the file is plaintext — abort and tell the user before any commit.

### 6. Full verify pass

```bash
task sops:verify
```

Must print `🎉 All *.sops.yaml files are properly encrypted`. If any file fails, re-encrypt that one too.

## Anti-patterns

- **NEVER** run `sops --encrypt` or `sops --decrypt` directly — always use the `task` wrapper (handles path rules correctly)
- **NEVER** commit a file that shows raw `stringData:` values without `ENC[` markers
- **NEVER** leave a decrypted file in the working tree between steps. Decrypt → edit → encrypt must be one contiguous sequence. No side quests.
- **NEVER** use `sed` or `echo >>` to append to a decrypted SOPS file — corrupts the YAML → encrypted file won't decrypt later

## Failure recovery

If re-encryption fails:

1. `task sops:verify` to see which file is broken
2. `git diff <file>` — if the diff shows large plaintext secrets, those are now staged-visible. Unstage: `git restore --staged <file>`
3. Try re-encrypting again: `task sops:encrypt-file file=<file>`
4. If still failing, check `.sops.yaml` `path_regex` matches the file path (often the issue when a file was moved across the `kubernetes/` boundary)

## Example session

```
User: change DiskStation password in homepage secret

1. task sops:verify                          → 🎉 all encrypted
2. task sops:decrypt-file file=kubernetes/apps/services/homepage/app/secret.sops.yaml
3. Edit: HOMEPAGE_VAR_DISKSTATION_PASS: <newvalue>
4. task sops:encrypt-file file=kubernetes/apps/services/homepage/app/secret.sops.yaml
5. rg -c "ENC\[AES256_GCM" kubernetes/apps/services/homepage/app/secret.sops.yaml  → 20
6. task sops:verify                          → 🎉 all encrypted
Done. Now safe to commit.
```

## What this skill does NOT do

- Does not commit changes — that's the user's call
- Does not push — belongs to session-close protocol
- Does not rotate age keys — out of scope
