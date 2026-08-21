#!/usr/bin/env bash
# Automated daily ShopGoodwill sweep for Adam: run -> sanity-check -> commit -> push.
# Installed as a cron job (10am Pacific). Summary goes to cron.log; the verbose
# per-query sweep output goes to cron_detail.log.
#
# Manual run:  /Users/als/sgw_claude/daily_sweep.sh
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

ROOT="/Users/als/sgw_claude"
PY="$ROOT/.venv/bin/python"
cd "$ROOT" || { echo "cannot cd to $ROOT"; exit 1; }

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') daily sweep start ====="

# Stay current with the remote in case of manual pushes between runs.
git pull --rebase --autostash origin main >/dev/null 2>&1 || echo "warn: git pull failed (continuing)"

# Run the sweep; verbose output to the detail log.
if ! "$ROOT/run_sweep.sh" adam >> "$ROOT/cron_detail.log" 2>&1; then
  echo "run_sweep.sh FAILED — not pushing (see cron_detail.log)"
  exit 1
fi

# Safety: never publish an empty/broken result (e.g. an SGW 403/outage returns 0).
COUNT=$("$PY" -c "import json;print(json.load(open('docs/data/adam.json'))['count'])" 2>/dev/null)
if [ -z "${COUNT:-}" ] || [ "$COUNT" -lt 20 ]; then
  echo "adam.json has only '${COUNT:-?}' items — looks broken (403/outage?). NOT pushing."
  exit 1
fi
NEW=$("$PY" -c "import json;d=json.load(open('docs/data/adam.json'));print(sum(1 for i in d['items'] if i.get('new')))" 2>/dev/null)

# Only commit/push if the data actually changed.
if git diff --quiet docs/data/adam.json; then
  echo "no change in adam.json ($COUNT items); nothing to push"
  exit 0
fi

git add docs/data/adam.json
git commit -q -m "Daily sweep (Adam): $COUNT items, $NEW new [automated]

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
if git push origin main >/dev/null 2>&1; then
  echo "pushed: $COUNT items, $NEW new"
else
  echo "git push FAILED (keychain locked / no network?) — commit is local"
  exit 1
fi
echo "===== $(date '+%H:%M:%S') done ====="
