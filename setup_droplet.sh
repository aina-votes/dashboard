#!/bin/bash
# One-shot installer for the Campaign Central Dashboard data refresher.
# Run on the droplet (159.89.148.51) as root:
#   curl -sSL https://raw.githubusercontent.com/aina-votes/dashboard/main/setup_droplet.sh | bash
set -euo pipefail

REPO_DIR=/root/campaign-dashboard
LOG_DIR=/root/logs
ENV_SRC=/root/fireflys-path/.env

if [ ! -f "$ENV_SRC" ]; then
  echo "FATAL: $ENV_SRC not found. Aborting." >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

if [ ! -d "$REPO_DIR/.git" ]; then
  rm -rf "$REPO_DIR"
  git clone https://github.com/aina-votes/dashboard.git "$REPO_DIR"
fi

cd "$REPO_DIR"
git pull --rebase origin main >/dev/null 2>&1 || true
ln -sf "$ENV_SRC" .env

# Ubuntu 24.04 is PEP 668 / externally-managed — prefer apt
if ! python3 -c "import requests, dotenv" 2>/dev/null; then
  apt-get update -qq
  apt-get install -y python3-requests python3-dotenv >/dev/null
fi
python3 -c "import requests, dotenv" || {
  echo "FATAL: requests/dotenv still missing after apt install" >&2
  exit 1
}

git config user.email "sampeck2550@gmail.com"
git config user.name  "Sam Peck"
TOKEN=$(grep '^GITHUB_TOKEN=' "$ENV_SRC" | cut -d= -f2-)
git remote set-url origin "https://aina-votes:${TOKEN}@github.com/aina-votes/dashboard.git"

# Refresh script: fetch -> if anything in data/ changed, commit + push
cat > /root/campaign-dashboard-refresh.sh <<'EOS'
#!/bin/bash
set -e
cd /root/campaign-dashboard
python3 fetch_central_progress.py >> /root/logs/campaign-dashboard.log 2>&1
# Stage data/ — central.json, per-campaign JSON, history JSONL files
git add data/
if ! git diff --cached --quiet; then
  git commit -m "auto: refresh dashboard data" >> /root/logs/campaign-dashboard.log 2>&1
  git push origin main >> /root/logs/campaign-dashboard.log 2>&1
fi
EOS
chmod +x /root/campaign-dashboard-refresh.sh

# Add cron entry (idempotent — strips any prior copy first)
(crontab -l 2>/dev/null | grep -v campaign-dashboard-refresh; \
 echo "*/30 * * * * /root/campaign-dashboard-refresh.sh") | crontab -

echo
echo "=== first run ==="
python3 fetch_central_progress.py

echo
echo "=== cron ==="
crontab -l | grep campaign-dashboard || echo "  (no entry — bug!)"

echo
echo "DONE."
