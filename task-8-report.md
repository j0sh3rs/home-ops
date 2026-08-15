# Task 8: OpenClaw Scheduled Hygiene Audit + GH-Issues Sweep

## Follow-up: Label Declaration Fix (2026-08-15)

Task 8 (41233f49) created the `automerge-candidate` label live via `gh label create` for the openclaw gh-issues sweep's eligibility gate. The repo's label-sync GitHub Actions workflow runs with `delete-other-labels: true`, which would silently delete any label not declared in `.github/labels.yaml`.

**Fix applied:** Added `automerge-candidate` to `.github/labels.yaml` with color `BFD4F2` and description "Eligible for automatic merge by openclaw gh-issues sweep". This ensures the label persists across label-sync runs.

Commit: (see parent commit message)
