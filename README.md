# Campaign Central Dashboard

Live: https://dashboard.ainavotes.com (planned takeover of existing election-stats site)

Single home for door + phone progress across all ʻĀina Votes campaigns. Home page = tiles per campaign; click a tile = detail page with split layout (doors | phones).

## What's here

- `index.html` — home page (password gate + 4 tiles + period toggle)
- `<key>.html` — per-campaign detail pages (Wave 2: jordan.html, christy.html, kalehua.html, paele.html)
- `shared/styles.css` — design tokens, layout, components
- `campaigns.py` — campaign config (chapters, saved list IDs, brand color)
- `goals.json` — per-campaign cycle goals (Sam edits as goals are set)
- `fetch_central_progress.py` — main refresh script, called every 30 min
- `setup_droplet.sh` — one-shot droplet installer
- `data/` — generated; never hand-edit
  - `central.json` — home-page payload
  - `<key>.json` — per-campaign detail payload
  - `history/<key>-doors.jsonl` — append-only doors snapshot log (powers doors line chart)

## Config Sam owns

### 1. `campaigns.py`
Update when a campaign joins, when Sam provides a saved list ID, or when a chapter changes.

For each campaign, the fields that need real values to surface data:
| Field | Means | Without it |
|---|---|---|
| `canvassed_list` | ST saved list ID for "all canvassed users" | doors count = 0 (tile shows "goal pending") |
| `to_call_list`   | ST saved list ID for the "to-call" universe (used in Wave 2) | phones universe display blank |
| `actions_chapter`| ST chapter where call logs land (Paele: 1514, Jordan: 901, Christy: 877) | phones count = 0 |

### 2. `goals.json`
Per-campaign totals. Monthly and weekly derive automatically unless you set the override fields. All zeros → tiles show "goal pending".

### 3. Password
The home page is gated by a SHA-256 hash in `index.html` (`PASS_HASH`). Rotate by:
1. Compute new hash: `python -c "import hashlib; print(hashlib.sha256(b'NEW_PASS').hexdigest())"`
2. Replace `PASS_HASH` in `index.html`
3. Bump `PASS_VERSION` (forces unlocked clients to re-auth)

Current placeholder hash gates against the word `lahui`. Replace before sharing the URL.

## Deploy

### First-time droplet setup
The droplet (159.89.148.51) needs `aina-votes/dashboard` GitHub repo to exist.

1. Create / repurpose the GitHub repo `aina-votes/dashboard`. If repurposing from the existing election-stats site, first move that content to a new repo or `stats.ainavotes.com`.
2. Push these files to `main`.
3. SSH to the droplet and run:
   ```
   curl -sSL https://raw.githubusercontent.com/aina-votes/dashboard/main/setup_droplet.sh | bash
   ```
4. Verify cron: `crontab -l | grep campaign-dashboard`
5. Verify first push: check the GitHub repo for an auto-commit on `data/central.json`.

### Subsequent updates
- Code/config changes: push to `main`. Cron pulls before each run.
- Manual refresh on droplet: `bash /root/campaign-dashboard-refresh.sh`
- Local dev refresh: from this directory, `python fetch_central_progress.py`

## Local dev

```
cd "C:/Firefly's Path/deployments/campaign-dashboard"
python fetch_central_progress.py            # writes data/
python -m http.server 8000                  # then open http://localhost:8000
```

## Status

**Wave 1 (this commit)**: Home page with 4 tiles, doors + phones bars per tile, period toggle, password gate. Refresh script. Droplet installer. Goals + saved list IDs are placeholders (0 / null) — Sam fills as they land.

**Wave 2 (next)**: Per-campaign detail pages with split layout (doors | phones), cumulative line charts, thermometer fills, per-brand styling. Retires `paele.ainavotes.com` standalone once parity confirmed.

## Open items

1. Saved list IDs for "all canvassed" per campaign — Sam to provide
2. Confirm Kalehua's chapters (1735 used for both voter + actions as fallback)
3. Goals per campaign — fill `goals.json` as Sam decides them
4. Brand specs — Christy missing entirely; Kalehua/Paele have palette PNGs only; only Jordan has local fonts. Wave 2 styling iterates against `Brand Guidelines/` at build time.
5. Existing `aina-votes/dashboard` repo (election stats) — decide takeover vs. relocate before pushing.
