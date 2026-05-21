"""
campaigns.py - canonical campaign config for the central dashboard.

One row per campaign tile. Edit here when:
 - A new campaign joins (e.g., Uncle Bobby)
 - Sam changes the doors-counting source
 - An ST chapter / org / saved-list ID changes

Source of truth for IDs:
 - Chapter IDs: .claude/skills/solidarity-tech/SKILL.md
 - Organization IDs: memory/reference_st_organizations.md (verified 2026-05-09)
 - Saved-list IDs: Sam (looked up in ST UI per campaign)
"""

# Each campaign:
#   key             - lowercase slug; matches brand css + data filename
#   name            - display name on the tile
#   candidate       - shown under tile title
#   primary_color   - dominant brand accent (tile rim on home page)
#   voter_chapter   - ST chapter for voter universe (used for doors property scan)
#   actions_chapters - list of ST chapter IDs where this campaign's calls log
#                      (one or more; we union calls across them for phones count)
#   org_id          - ST organization id (informational; /calls?organization_id is silently ignored)
#   doors_baseline  - knocks completed BEFORE dashboard launch. Excluded from
#                     weekly/monthly counts (so those start at 0 today and climb).
#                     Included in total count + total goal so the total view
#                     shows credit for pre-existing work.
#   canvassed_list_id      - ST saved-list ID for "canvassed users" (Paele/Kalehua)
#   canvassed_property_slug - ST custom-user-property slug to count when not blank
#                             (Jordan/Christy use 'last-canvass-status')
#   phase_start_date - ISO date the current phone/door phase officially started.
#                     Used as `_since` cutoff on /calls so we don't pick up
#                     pre-campaign call activity logged into the same chapter.
#   goal_end_date   - ISO date for ballot drop / phase end (goal math anchors here)
#
# Exactly one of (canvassed_list_id, canvassed_property_slug) should be set per campaign.
CAMPAIGNS = [
    {
        "key": "jordan",
        "name": "Jordan for Hawaii",
        "candidate": "Jordan Nakamura",
        "primary_color": "#D4FF00",
        "voter_chapter": 1736,
        "org_id": 738,
        "actions_chapters": [1736, 901], # voter chapter (where most calls land) + volunteers chapter
        "canvassed_list_id": 41845,      # "Jordan canvassed" saved list
        "canvassed_property_slug": None,
        "doors_baseline": 3934,          # list size at dashboard launch 2026-05-21
        "phase_start_date": "2026-05-19",
        "goal_end_date": "2026-07-21",
    },
    {
        "key": "christy",
        "name": "Christy for Hawaii",
        "candidate": "Christy Macpherson",
        "primary_color": "#3DD9A1",
        "voter_chapter": 1423,
        "org_id": 542,
        "actions_chapters": [1423, 877], # voter chapter (where most calls land) + volunteers chapter
        "canvassed_list_id": 41844,      # "Christy canvassed" saved list
        "canvassed_property_slug": None,
        "doors_baseline": 2113,          # pre-launch canvasses (Sam-confirmed); set to current list size at launch
        "phase_start_date": "2026-05-19",
        "goal_end_date": "2026-07-21",
    },
    {
        "key": "kalehua",
        "name": "Kalehua for Hawaii",
        "candidate": "Kalehua Kaopua",
        "primary_color": "#1B3A2C",
        "voter_chapter": 1744,
        "org_id": 743,
        "actions_chapters": [1744, 1743], # voter chapter (where calls likely land) + volunteers chapter
        "canvassed_list_id": 41764,
        "canvassed_property_slug": None,
        "doors_baseline": 0,
        "phase_start_date": "2026-05-19",
        "goal_end_date": "2026-07-21",
    },
    {
        "key": "paele",
        "name": "Vote Paele",
        "candidate": "Paele Kiakona",
        "primary_color": "#B8542A",
        "voter_chapter": 1790,
        "org_id": 773,
        "actions_chapters": [1790, 1514], # voter chapter + campaign chapter
        "canvassed_list_id": 41208,
        "canvassed_property_slug": None,
        "doors_baseline": 56,
        "phase_start_date": "2026-05-11",
        "goal_end_date": "2026-07-21",
    },
]


def by_key(key: str):
    for c in CAMPAIGNS:
        if c["key"] == key:
            return c
    raise KeyError(f"unknown campaign: {key}")
