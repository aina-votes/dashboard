#!/usr/bin/env python3
"""
fetch_central_progress.py
==========================
Pulls live progress for every campaign in campaigns.py and writes:
  data/central.json   - home-page tile data (door + phone counts per campaign)
  data/<key>.json     - per-campaign detail data (time-series + goals)
  data/history/<key>-doors.jsonl - append-only doors snapshot log

Designed to run on a 30-min cron alongside the existing Paele/Jordan refreshers.

For each campaign, makes ST API calls:
  Doors path A (saved list):  GET /users?user_list_ids=<list>&_limit=1 -> meta.total_count
  Doors path B (property scan): paginate GET /users?chapter_ids=<voter>;
                                 count users where custom_user_properties[<slug>] is set
  Phones: GET /calls?organization_id=<org_id> -> paginated, bucket by HST day

If a campaign is missing config (no list_id, no property_slug, no org_id),
that side reports count=0 and the dashboard renders a "goal pending" state.
"""

import os, sys, json, time, requests
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding='utf-8')
local_env = ROOT / ".env"
if local_env.exists():
    load_dotenv(local_env)
else:
    load_dotenv(r"C:\Firefly's Path\.env")

sys.path.insert(0, str(ROOT))
from campaigns import CAMPAIGNS

ST_BASE = "https://api.solidarity.tech/v1"
ST_API_KEY = os.environ["ST_API_KEY"]
HEADERS = {"Authorization": f"Bearer {ST_API_KEY}"}

HST = timezone(timedelta(hours=-10))
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(exist_ok=True)


def hst_today() -> date:
    return datetime.now(HST).date()


def hst_date(iso_ts: str) -> date:
    return datetime.fromisoformat(iso_ts).astimezone(HST).date()


def st_get(path: str, params: dict, attempts: int = 4):
    """GET with exponential backoff on connection errors / 5xx / 429."""
    delay = 1.0
    for i in range(attempts):
        try:
            r = requests.get(f"{ST_BASE}{path}", headers=HEADERS, params=params, timeout=45)
            if r.status_code >= 500 or r.status_code == 429:
                raise requests.HTTPError(f"{r.status_code} on {path}", response=r)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.HTTPError) as e:
            if i == attempts - 1:
                raise
            print(f"  retry {i+1}/{attempts} after {delay:.1f}s ({type(e).__name__})")
            time.sleep(delay)
            delay *= 2


def fetch_list_total(list_id) -> int:
    """ST saved-list size via meta.total_count. Returns 0 if list_id is falsy."""
    if not list_id:
        return 0
    j = st_get("/users", {"user_list_ids": list_id, "_limit": 1})
    return int(j.get("meta", {}).get("total_count", 0) or 0)


_USERS_SNAPSHOT_CACHE = None

def _users_snapshot():
    """Load & cache st_data/users.json. Looks for the snapshot at:
       1) <project_root>/st_data/users.json (Windows dev + droplet clone)
       2) /root/fireflys-path/st_data/users.json (droplet absolute)
    """
    global _USERS_SNAPSHOT_CACHE
    if _USERS_SNAPSHOT_CACHE is not None:
        return _USERS_SNAPSHOT_CACHE
    candidates = [
        ROOT.parents[1] / "st_data" / "users.json",      # repo root from deployments/<x>/
        Path("/root/fireflys-path/st_data/users.json"),
        Path(r"C:\Firefly's Path\st_data\users.json"),
    ]
    for p in candidates:
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            _USERS_SNAPSHOT_CACHE = (d.get("data") or d, p)
            print(f"  snapshot: {p} ({len(_USERS_SNAPSHOT_CACHE[0])} users)")
            return _USERS_SNAPSHOT_CACHE
    print(f"  WARN: st_data/users.json not found; property-scan counts will be 0")
    _USERS_SNAPSHOT_CACHE = ([], None)
    return _USERS_SNAPSHOT_CACHE


def count_users_with_property_set(chapter_id: int, slug: str) -> int:
    """
    Count users in <chapter_id> whose custom_user_properties[<slug>] is
    truthy (not None, not empty string, not empty list).

    Reads the local ST snapshot at st_data/users.json. The snapshot is
    refreshed separately by .claude/skills/solidarity-tech/tools/refresh_st_data.py
    on its own cron (see README for droplet setup).
    """
    if not chapter_id or not slug:
        return 0
    users, _ = _users_snapshot()
    n = 0
    for u in users:
        if chapter_id not in (u.get("chapter_ids") or []):
            continue
        cup = u.get("custom_user_properties") or {}
        v = cup.get(slug)
        if v not in (None, "", []):
            n += 1
    return n


_CALLS_CACHE = {}  # since_iso -> list of all calls since then (cached per run)

def fetch_all_calls_since(since_iso: str):
    """Paginate /calls?_since=YYYY-MM-DD WITHOUT any chapter filter.

    Gotcha (verified 2026-05-21): when both `chapter_id` and `_since` are
    sent on /calls, the chapter_id filter is silently ignored and the
    endpoint returns ALL calls since the date regardless of chapter.
    So we pull once globally and filter chapter client-side.
    """
    if not since_iso:
        return []
    if since_iso in _CALLS_CACHE:
        return _CALLS_CACHE[since_iso]
    rows = []
    offset = 0
    limit = 100
    while True:
        j = st_get("/calls", {"_limit": limit, "_offset": offset, "_since": since_iso})
        page = j.get("data", [])
        if not page:
            break
        rows.extend(page)
        if len(page) < limit:
            break
        offset += limit
        time.sleep(0.3)
        if offset > 50_000:
            break
    _CALLS_CACHE[since_iso] = rows
    return rows


def fetch_calls_for_chapters(chapter_ids, since_iso: str):
    """Pull all calls since since_iso once, then filter client-side to
    those whose chapter_id is in chapter_ids."""
    if not chapter_ids or not since_iso:
        return []
    chapter_set = set(chapter_ids)
    return [c for c in fetch_all_calls_since(since_iso)
            if c.get("chapter_id") in chapter_set and c.get("created_at")]


def load_goals():
    return json.loads((ROOT / "goals.json").read_text(encoding="utf-8"))


def phase_total_days(phase_start_iso: str, phase_end_iso: str) -> int:
    """Days from phase_start through phase_end inclusive (>= 1)."""
    s = datetime.fromisoformat(phase_start_iso).date()
    e = datetime.fromisoformat(phase_end_iso).date()
    return max(1, (e - s).days + 1)


def derive_period_goals(total: int, phase_start_iso: str, phase_end_iso: str,
                        weekly_override, monthly_override):
    """Constant-pace per-period targets across the full phase length, matching
    the GOTV phase builder's formula. weekly/monthly stay fixed for the whole
    phase rather than ratcheting up as time runs out — that's what Sam plans
    against. Overrides bypass the formula entirely.
    """
    if total <= 0:
        return 0, 0
    days = phase_total_days(phase_start_iso, phase_end_iso)
    monthly = monthly_override if monthly_override else round(total * 30 / days)
    weekly = weekly_override if weekly_override else round(total * 7 / days)
    return int(weekly), int(monthly)


def week_window(today: date):
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def month_window(today: date):
    first = today.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    last = nxt - timedelta(days=1)
    return first, last


def call_dates(calls):
    return [hst_date(c["created_at"]) for c in calls]


def bucket_daily(dates, start: date, end: date):
    """Return list of {date, count} from start..end inclusive."""
    counts = {}
    for d in dates:
        counts[d] = counts.get(d, 0) + 1
    out = []
    d = start
    while d <= end:
        out.append({"date": d.isoformat(), "count": counts.get(d, 0)})
        d += timedelta(days=1)
    return out


def append_doors_snapshot(key: str, count: int):
    """Append-only JSONL: {ts, count}. Powers the doors-side line chart."""
    line = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "count": int(count),
    }) + "\n"
    (HISTORY_DIR / f"{key}-doors.jsonl").open("a", encoding="utf-8").write(line)


def read_doors_history(key: str):
    """Return list of {ts, count} snapshots, oldest first."""
    p = HISTORY_DIR / f"{key}-doors.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def doors_daily_from_history(key: str, today: date):
    """Collapse history snapshots to one cumulative count per HST day
    (last value of the day, forward-filled). Each entry's count is the
    cumulative snapshot value at end of that day."""
    history = read_doors_history(key)
    by_day = {}
    for s in history:
        d = datetime.fromisoformat(s["ts"]).astimezone(HST).date()
        by_day[d] = s["count"]
    if not by_day:
        return []
    first = min(by_day)
    out = []
    d = first
    last = 0
    while d <= today:
        if d in by_day:
            last = by_day[d]
        out.append({"date": d.isoformat(), "count": last})
        d += timedelta(days=1)
    return out


def doors_deltas_per_day(key: str, baseline: int, today: date):
    """Convert cumulative-snapshot history into per-day NEW knocks (>=0),
    using baseline as the implicit floor at launch. Per-day delta = max(0,
    today_snapshot - max(yesterday_snapshot, baseline))."""
    cum_series = doors_daily_from_history(key, today)
    if not cum_series:
        return []
    out = []
    prev = baseline
    for p in cum_series:
        cur = p["count"]
        delta = max(0, cur - max(prev, baseline))
        out.append({"date": p["date"], "count": delta})
        prev = cur
    return out


def sum_in_range(series, lo_iso: str, hi_iso: str) -> int:
    return sum(b["count"] for b in series if lo_iso <= b["date"] <= hi_iso)


def compute_side(count: int, daily_series, total_goal: int, weekly_goal: int,
                 monthly_goal: int, today: date):
    """Build the common side-payload (doors or phones) the UI consumes."""
    wk_lo, wk_hi = week_window(today)
    mo_lo, mo_hi = month_window(today)
    week_count = sum(b["count"] for b in daily_series
                     if wk_lo.isoformat() <= b["date"] <= wk_hi.isoformat())
    month_count = sum(b["count"] for b in daily_series
                      if mo_lo.isoformat() <= b["date"] <= mo_hi.isoformat())

    def pct(num, denom):
        return round(100 * num / denom, 1) if denom > 0 else 0

    return {
        "count_total": int(count),
        "count_week": int(week_count),
        "count_month": int(month_count),
        "goal_total": int(total_goal),
        "goal_weekly": int(weekly_goal),
        "goal_monthly": int(monthly_goal),
        "pct_total": pct(count, total_goal),
        "pct_week": pct(week_count, weekly_goal),
        "pct_month": pct(month_count, monthly_goal),
        "week_window": [wk_lo.isoformat(), wk_hi.isoformat()],
        "month_window": [mo_lo.isoformat(), mo_hi.isoformat()],
        "daily_series": daily_series,
        "has_goal": total_goal > 0,
    }


def process_campaign(c: dict, goals: dict, today: date):
    g = goals.get(c["key"], {})
    goal_end = c.get("goal_end_date") or c.get("primary_date")
    phase_start = c.get("phase_start_date") or "2026-01-01"

    # ---- Doors side ----
    if c.get("canvassed_list_id"):
        doors_source = f"list:{c['canvassed_list_id']}"
        doors_count = fetch_list_total(c["canvassed_list_id"])
    elif c.get("canvassed_property_slug"):
        doors_source = f"prop:{c['canvassed_property_slug']}@{c['voter_chapter']}"
        doors_count = count_users_with_property_set(
            c["voter_chapter"], c["canvassed_property_slug"]
        )
    else:
        doors_source = "(none configured)"
        doors_count = 0
    print(f"  doors source: {doors_source} -> {doors_count}")

    append_doors_snapshot(c["key"], doors_count)

    baseline = int(c.get("doors_baseline", 0) or 0)
    doors_delta_series = doors_deltas_per_day(c["key"], baseline, today)

    configured_doors_goal = int(g.get("doors_total", 0) or 0)
    displayed_doors_goal = configured_doors_goal + baseline
    doors_weekly_goal, doors_monthly_goal = derive_period_goals(
        configured_doors_goal, phase_start, goal_end,
        g.get("doors_weekly_override"), g.get("doors_monthly_override"),
    )

    # Weekly / monthly: NEW knocks within window (excludes baseline by default)
    wk_lo, wk_hi = week_window(today)
    mo_lo, mo_hi = month_window(today)
    doors_week  = sum_in_range(doors_delta_series, wk_lo.isoformat(), wk_hi.isoformat())
    doors_month = sum_in_range(doors_delta_series, mo_lo.isoformat(), mo_hi.isoformat())

    # Baseline credit: knocks done before the first snapshot are dated as an
    # unknown spread across [phase_start, first_snapshot - 1]. Credit them to
    # a period iff that period FULLY contains the baseline window — keeps
    # Paele's 56 in May (where they happened) without dumping Jordan's 3934
    # legacy knocks into May counts when most happened earlier.
    first_snap_iso = doors_delta_series[0]["date"] if doors_delta_series else None
    baseline_end_iso = None
    if first_snap_iso:
        baseline_end_iso = (datetime.fromisoformat(first_snap_iso).date()
                            - timedelta(days=1)).isoformat()

    def period_covers_baseline(p_lo_iso: str, p_hi_iso: str) -> bool:
        if not baseline or not baseline_end_iso: return False
        return p_lo_iso <= phase_start and baseline_end_iso <= p_hi_iso

    # Pre-launch knocks aren't dated per-day, so we never attribute them to a
    # single week (would inflate Jordan/Christy whose narrow baseline windows
    # technically fit in the current week). Month + custom use the coverage
    # rule — same rule applied uniformly across all campaigns.
    baseline_in_week  = False
    baseline_in_month = period_covers_baseline(mo_lo.isoformat(), mo_hi.isoformat())
    if baseline_in_month: doors_month += baseline

    def pct(num, denom):
        return round(100 * num / denom, 1) if denom > 0 else 0

    doors = {
        "count_total": int(doors_count),
        "count_week":  int(doors_week),
        "count_month": int(doors_month),
        "goal_total":  int(displayed_doors_goal),
        "goal_weekly": int(doors_weekly_goal),
        "goal_monthly":int(doors_monthly_goal),
        "pct_total":   pct(doors_count, displayed_doors_goal),
        "pct_week":    pct(doors_week,  doors_weekly_goal),
        "pct_month":   pct(doors_month, doors_monthly_goal),
        "week_window": [wk_lo.isoformat(), wk_hi.isoformat()],
        "month_window":[mo_lo.isoformat(), mo_hi.isoformat()],
        "daily_series":doors_delta_series,
        "baseline":    baseline,
        "baseline_in_week":  baseline_in_week,
        "baseline_in_month": baseline_in_month,
        "baseline_end_date": baseline_end_iso,
        "has_goal":    displayed_doors_goal > 0,
    }

    # ---- Phones side ----
    # `_since` bounded by the campaign's phone phase start; without it we
    # pick up pre-campaign call history (other orgs/efforts in the same chapter).
    calls = fetch_calls_for_chapters(c.get("actions_chapters") or [], phase_start)
    phones_count = len(calls)
    if calls:
        cdates = call_dates(calls)
        first_call = min(cdates)
        phones_series = bucket_daily(cdates, first_call, today)
    else:
        phones_series = []

    phones_total_goal = int(g.get("phones_total", 0) or 0)
    phones_weekly, phones_monthly = derive_period_goals(
        phones_total_goal, phase_start, goal_end,
        g.get("phones_weekly_override"), g.get("phones_monthly_override"),
    )
    phones = compute_side(phones_count, phones_series,
                          phones_total_goal, phones_weekly, phones_monthly, today)

    warnings = []
    if not c.get("canvassed_list_id") and not c.get("canvassed_property_slug"):
        warnings.append("no doors source configured (canvassed_list_id or canvassed_property_slug)")
    if not c.get("actions_chapters"):
        warnings.append("actions_chapters not configured - phones count is 0")

    detail = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "key": c["key"],
        "name": c["name"],
        "candidate": c["candidate"],
        "primary_color": c["primary_color"],
        "phase_start_date": phase_start,
        "goal_end_date": goal_end,
        "phase_total_days": phase_total_days(phase_start, goal_end),
        "doors_source": doors_source,
        "doors": doors,
        "phones": phones,
        "data_warnings": warnings,
    }

    tile = {
        "key": c["key"],
        "name": c["name"],
        "candidate": c["candidate"],
        "primary_color": c["primary_color"],
        "doors": {k: doors[k] for k in
                  ("count_total", "count_week", "count_month",
                   "goal_total", "goal_weekly", "goal_monthly",
                   "pct_total", "pct_week", "pct_month", "has_goal", "baseline")},
        "phones": {k: phones[k] for k in
                   ("count_total", "count_week", "count_month",
                    "goal_total", "goal_weekly", "goal_monthly",
                    "pct_total", "pct_week", "pct_month", "has_goal")},
    }

    return tile, detail


def main():
    today = hst_today()
    goals = load_goals()

    # Preserve prior tiles so a transient API failure (e.g. 429 on /calls) doesn't
    # drop a campaign from the home page entirely. On error, re-emit the previous
    # tile flagged stale rather than omitting the campaign.
    prev_central_path = DATA_DIR / "central.json"
    prev_tile_by_key: dict[str, dict] = {}
    if prev_central_path.exists():
        try:
            prev = json.loads(prev_central_path.read_text(encoding="utf-8"))
            for t in prev.get("campaigns", []):
                if t.get("key"):
                    prev_tile_by_key[t["key"]] = t
        except (json.JSONDecodeError, OSError):
            pass

    def fallback_tile(c, err):
        prior = prev_tile_by_key.get(c["key"])
        if not prior:
            print(f"  → no prior tile to fall back to; campaign omitted")
            return None
        stale = dict(prior)
        stale["stale"] = True
        stale["stale_reason"] = f"{type(err).__name__}: {err}"
        print(f"  → keeping prior tile (marked stale)")
        return stale

    tiles = []
    for c in CAMPAIGNS:
        print(f"\n=== {c['name']} ({c['key']}) ===")
        try:
            tile, detail = process_campaign(c, goals, today)
        except requests.exceptions.RequestException as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            t = fallback_tile(c, e)
            if t: tiles.append(t)
            continue
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            t = fallback_tile(c, e)
            if t: tiles.append(t)
            continue

        tiles.append(tile)
        (DATA_DIR / f"{c['key']}.json").write_text(
            json.dumps(detail, indent=2), encoding="utf-8")

        print(f"  doors:  {detail['doors']['count_total']:>5}  "
              f"goal {detail['doors']['goal_total']:>5}  "
              f"pct {detail['doors']['pct_total']:.1f}%")
        print(f"  phones: {detail['phones']['count_total']:>5}  "
              f"goal {detail['phones']['goal_total']:>5}  "
              f"pct {detail['phones']['pct_total']:.1f}%")

    central = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "campaigns": tiles,
    }
    (DATA_DIR / "central.json").write_text(
        json.dumps(central, indent=2), encoding="utf-8")
    print(f"\nwrote {DATA_DIR / 'central.json'} ({len(tiles)} campaigns)")


if __name__ == "__main__":
    main()
