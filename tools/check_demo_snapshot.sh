#!/usr/bin/env bash
# Pre-deploy guard for the public demo snapshot.
#
# Set this as the Cloudflare Pages "build command". The site itself needs no
# build — this exists only to fail the deploy if the snapshot carries anything
# that must not be public. It replaces the identical check that lived in
# .github/workflows/deploy-demo.yml before the demo moved to Cloudflare; losing
# it along with that workflow would have quietly removed the only automated
# thing standing between a mis-built snapshot and a public URL.
#
# Run locally the same way:  bash tools/check_demo_snapshot.sh

set -euo pipefail

CORPUS="demo/data/corpus.json"

if [ ! -f "$CORPUS" ]; then
  echo "FAIL: $CORPUS is missing — was the snapshot ever built?" >&2
  exit 1
fi

# 1. Per-set economics must never reach a public page.
if grep -q '"costs_included":[[:space:]]*true' "$CORPUS"; then
  echo "FAIL: snapshot was built with --include-costs. Rebuild without it:" >&2
  echo "      python tools/build_demo_snapshot.py" >&2
  exit 1
fi

# 2. Cost and token fields must not appear anywhere in the payload, even if the
#    flag above says otherwise — the flag is a claim, this is the evidence.
if grep -rlE '"(gen|judge|solver)_(cost_usd|input_tokens|output_tokens)"|"total_cost_usd"' \
     demo/data 2>/dev/null | head -1 | grep -q .; then
  echo "FAIL: cost or token fields found in demo/data — rebuild the snapshot." >&2
  grep -rlE '"(gen|judge|solver)_(cost_usd|input_tokens|output_tokens)"|"total_cost_usd"' \
    demo/data | sed 's/^/      /' >&2
  exit 1
fi

SETS=$(grep -o '"sets_total":[0-9]*' "$CORPUS" | head -1 | cut -d: -f2)
echo "snapshot guard passed — ${SETS:-?} sets, no cost or token fields present"
