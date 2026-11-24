#!/usr/bin/env bash
# Fail when an app consumes a Secret via envFrom/secretKeyRef but has no
# Reloader annotation — rotated keys would stay stale until a manual
# rollout (issue #493 class). Pattern of record:
#   kubernetes/apps/ai/atuin-ai-server/app/helmrelease.yaml
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fail=0
while IFS= read -r f; do
  if ! grep -q "reloader.stakater.com/" "$f"; then
    echo "FAIL: $f references a secret without a reloader.stakater.com/ annotation"
    fail=1
  else
    echo "PASS: $f"
  fi
done < <(grep -rl -E "secretRef|secretKeyRef" kubernetes/apps --include="*helmrelease.yaml")

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "Fix: add at controller level (under values.controllers.<app>):"
  echo "    annotations:"
  echo '      reloader.stakater.com/auto: "true"'
  exit 1
fi
echo "All secret-consuming apps have Reloader annotations."
