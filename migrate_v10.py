#!/usr/bin/env python3
from pathlib import Path
import base64, hashlib, zlib

ROOT=Path(__file__).resolve().parent
EXPECTED_SHA256="6440cc6c60e22c8a7477049caac30d213ba0092a66468122081063907aeba98f"

parts=[]
for i in range(8):
    p=ROOT/f"v10_payload_{i:02d}.txt"
    if not p.exists():
        raise SystemExit(f"Payload V10 manquant: {p.name}")
    parts.append(p.read_text(encoding="utf-8").strip())

try:
    bot_bytes=zlib.decompress(base64.b64decode("".join(parts)))
except Exception as exc:
    raise SystemExit(f"Payload V10 illisible: {exc}")

actual=hashlib.sha256(bot_bytes).hexdigest()
if actual!=EXPECTED_SHA256:
    raise SystemExit(f"SHA256 V10 invalide: {actual}")

bot=bot_bytes.decode("utf-8")
if 'VERSION="10.0.0"' not in bot or 'FEATURE_VERSION="10.0"' not in bot:
    raise SystemExit("Payload V10 valide cryptographiquement mais version attendue absente")

(ROOT/"bot.py").write_text(bot,encoding="utf-8")

clean_workflow=r'''name: MLB Betting Bot V10

on:
  workflow_dispatch:
  schedule:
    - cron: "17 16 * * *"
      timezone: "Europe/Paris"
    - cron: "17 20 * * *"
      timezone: "Europe/Paris"
    - cron: "47 23 * * *"
      timezone: "Europe/Paris"
    - cron: "17 2 * * *"
      timezone: "Europe/Paris"

permissions:
  contents: write

concurrency:
  group: mlb-betting-bot-v10
  cancel-in-progress: false

jobs:
  run-bot:
    name: Exécution du Bot V10
    runs-on: ubuntu-latest
    timeout-minutes: 40

    steps:
      - name: Récupération du repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: true

      - name: Installation de Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Validation Python V10
        run: |
          python --version
          python -m py_compile bot.py
          python bot.py --self-test

      - name: Exécution du Bot V10
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          BANKROLL: ${{ vars.BANKROLL }}
          UNIT: ${{ vars.UNIT }}
          MAX_STAKE_UNITS: ${{ vars.MAX_STAKE_UNITS }}
          MIN_EV: ${{ vars.MIN_EV }}
          MIN_EDGE: ${{ vars.MIN_EDGE }}
          MAX_DAILY_EXPOSURE_PCT: "0.30"
          MAX_GAME_EXPOSURE_PCT: "0.15"
          MAX_COMBO_EXPOSURE_PCT: "0.05"
          HISTORY_FILE: data/mlb_history_v10.jsonl
          MATCH_MAX_DELTA_HOURS: "2.0"
          ARCHIVE_AFTER_DAYS: "60"
        run: |
          mkdir -p data
          python bot.py

      - name: Validation données V10
        if: success()
        run: |
          python - <<'PY'
          import json
          from pathlib import Path
          paths=[Path('data/mlb_history_v10.jsonl')]
          paths += sorted(Path('data/archive_v10').glob('*.jsonl')) if Path('data/archive_v10').exists() else []
          for p in paths:
              if not p.exists():
                  continue
              for line in p.read_text(encoding='utf-8').splitlines():
                  if line.strip():
                      json.loads(line)
              print(f'{p}: valide')
          PY

      - name: Sauvegarde historique V10
        if: success()
        run: |
          git config user.name "MLB Betting Bot"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/mlb_history_v10.jsonl data/archive_v10 2>/dev/null || true
          if git diff --cached --quiet; then
            echo "Données V10 inchangées."
            exit 0
          fi
          git commit -m "data: update V10 model history [skip ci]"
          git pull --rebase origin main
          git push
'''
workflow=ROOT/".github/workflows/mlb-bot.yml"
workflow.write_text(clean_workflow,encoding="utf-8")

for i in range(8):
    (ROOT/f"v10_payload_{i:02d}.txt").unlink(missing_ok=True)
Path(__file__).unlink(missing_ok=True)

print(f"Migration V10 appliquée • bot.py SHA256={actual}")
print("bot.py est désormais la source de vérité; le workflow ne modifie plus le code.")
