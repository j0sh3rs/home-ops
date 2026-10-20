#!/bin/bash
# Usage: ./memsample.sh <pid> > results/mem-<label>.csv   (Mac only)
set -euo pipefail
pid=$1
echo "epoch,rss_mb,mem_free_pct"
while ps -p "$pid" >/dev/null 2>&1; do
  rss=$(ps -o rss= -p "$pid" | tr -d ' ')
  free=$(memory_pressure | awk -F': ' '/free percentage/ {gsub("%","",$2); print $2}')
  echo "$(date +%s),$((rss / 1024)),$free"
  sleep 1
done
