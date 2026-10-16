#!/bin/bash
# Runs offline after the agent finishes. Never download anything here.
# Exit 10 means a completed semantic rejection; other failures are verifier errors.
set -eu
mkdir -p /logs/verifier
rm -f /logs/verifier/reward.txt
rc=0
python3 /tests/verify.py || rc=$?
case "$rc" in
  0) echo 1 > /logs/verifier/reward.txt ;;
  10) echo 0 > /logs/verifier/reward.txt ;;
  *) echo "VERIFIER_ERROR: exit $rc" >&2; exit "$rc" ;;
esac
