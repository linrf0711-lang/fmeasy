#!/usr/bin/env python3
"""Build compact, browser-friendly FMEASY squad files from public dataset mirrors."""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "squads"

SOURCES = {
    2004: {
        "url": "https://raw.githubusercontent.com/lbenz730/fifa_model/master/player_stats.csv",
        "label": "FIFA Index · FIFA 05 历史数据",
        "filter_year": 2005,
    },
    2021: {
        "url": "https://raw.githubusercontent.com/abineshta/FIFA-22-complete-player-dataset-EDA/main/players_22.csv",
        "label": "Kaggle · FIFA 22 Complete Player Dataset",
    },
    2022: {
        "url": "https://raw.githubusercontent.com/sumairrathore/Project_4/main/data/raw_data/players_23.csv",
        "label": "Kaggle · FIFA 23 Complete Player Dataset",
    },
    2023: {
        "url": "https://raw.githubusercontent.com/elouanzer/AAAproject_FC24/main/male_players.csv",
        "label": "Kaggle · EA Sports FC 24 Complete Player Dataset",
    },
    2024: {
        "url": "https://raw.githubusercontent.com/datasosa/FC25_Player_Analysis/main/player-data-full-2025-june.csv",
        "label": "EA Sports FC 25 社区数据库（Kaggle 字段兼容）",
    },
    2025: {
        "url": "https://raw.githubusercontent.com/Wrexist/dynasty-manager/main/FC26_20250921.csv",
        "label": "Kaggle · FC 26 Player Data",
    },
}

TOP_LEAGUE_PATTERNS = (
    "premier league",
    "england first division",
    "spain primera division",
    "primera división",
    "la liga",
    "german 1. bundesliga",
    "bundesliga",
    "italian serie a",
    "serie a",
    "french ligue 1",
    "ligue 1",
)

SECOND_TIER_PATTERNS = (
    "2. bundesliga",
    "bundesliga 2",
    "serie b",
    "ligue 2",
    "segunda",
    "championship",
)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "FMEASY-squad-builder/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read()
    return raw.decode("utf-8-sig", errors="replace")


def clean(value) -> str:
    return str(value or "").strip()


def first(row: dict[str, str], *names: str) -> str:
    lowered = {str(key).strip().lower(): value for key, value in row.items() if key is not None}
    for name in names:
        value = lowered.get(name.lower())
        if clean(value):
            return clean(value)
    return ""


def number(value, default=None):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def money_millions(value):
    raw = clean(value).replace("€", "").replace("£", "").replace("$", "").replace(",", "")
    if not raw:
        return None
    multiplier = 1
    if raw[-1:].upper() == "M":
        multiplier, raw = 1_000_000, raw[:-1]
    elif raw[-1:].upper() == "K":
        multiplier, raw = 1_000, raw[:-1]
    amount = number(raw)
    if amount is None or amount <= 0:
        return None
    return round(amount * multiplier / 1_000_000, 2)


def is_top_league(league: str) -> bool:
    value = clean(league).lower()
    if not value:
        return True
    if any(pattern in value for pattern in SECOND_TIER_PATTERNS):
        return False
    return any(pattern in value for pattern in TOP_LEAGUE_PATTERNS)


def row_matches_edition(row: dict[str, str], edition: int) -> bool:
    year = number(first(row, "year", "fifa_version", "version"))
    season = clean(first(row, "season")).lstrip("0")
    return (year is not None and int(year) == edition) or season == str(edition)[-2:].lstrip("0")


def normalize_player(row: dict[str, str], start_year: int, source: str):
    name = first(row, "short_name", "name", "full_name", "long_name", "player_name")
    name = re.sub(r"\s+-\s*$", "", name).strip()
    club = first(row, "club_name", "club", "team_name", "team")
    league = first(row, "league_name", "club_league_name", "league", "competition")
    if not name or not club or club.lower() in {"free agents", "free agent", "nan", "none"}:
        return None
    if start_year != 2004 and not is_top_league(league):
        return None

    overall = number(first(row, "overall", "overall_rating", "overallrating", "rating", "ovr"))
    if overall is None:
        return None
    potential = number(first(row, "potential", "pot"), overall)
    age = number(first(row, "age"))
    birth = first(row, "dob", "birthdate", "date_of_birth")
    if age is None and birth:
        match = re.search(r"(19|20)\d{2}", birth)
        if match:
            age = start_year - int(match.group())
    if age is None:
        age = 24

    raw_position = first(
        row,
        "player_positions",
        "preferred_positions",
        "positions",
        "club_position",
        "position",
        "preferredposition1",
    )
    jersey = number(first(row, "club_jersey_number", "jersey_number", "number", "club_kit_number"))
    value = money_millions(first(row, "value_eur", "value", "market_value", "marketvalue"))
    loan_from = first(row, "club_loaned_from", "loaned_from", "loan_from")
    club_position = first(row, "club_position").upper()
    role = "后备／青年" if club_position in {"RES", "U21", "U19"} else "一线队"

    player = {
        "name": name,
        "sourcePos": raw_position or "CM",
        "age": max(15, min(45, int(round(age)))),
        "overall": max(40, min(99, int(round(overall)))),
        "potential": max(40, min(99, int(round(potential)))),
        "role": role,
        "source": source,
    }
    if jersey is not None and 0 < jersey < 100:
        player["number"] = int(jersey)
    if value is not None:
        player["marketValue"] = value
    if loan_from:
        player["loanFrom"] = loan_from
    player_id = first(row, "sofifa_id", "player_id", "playerid", "id")
    return club, player_id, player


def build_one(start_year: int, config: dict):
    print(f"Downloading {start_year}: {config['url']}", flush=True)
    text = fetch_text(config["url"])
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise RuntimeError(f"No CSV header for {start_year}")

    teams: dict[str, dict[str, dict]] = defaultdict(dict)
    read_rows = kept_rows = 0
    for row in reader:
        read_rows += 1
        edition = config.get("filter_year")
        if edition and not row_matches_edition(row, edition):
            continue
        normalized = normalize_player(row, start_year, config["label"])
        if not normalized:
            continue
        club, player_id, player = normalized
        key = player_id or re.sub(r"[^a-z0-9]", "", player["name"].lower())
        previous = teams[club].get(key)
        if previous is None or player["overall"] > previous["overall"]:
            teams[club][key] = player
        kept_rows += 1

    packed = {
        club: sorted(players.values(), key=lambda item: (-item["overall"], item["name"]))[:35]
        for club, players in sorted(teams.items())
        if len(players) >= 8
    }
    player_count = sum(len(players) for players in packed.values())
    if len(packed) < 15 or player_count < 250:
        raise RuntimeError(
            f"Implausible {start_year} output: {len(packed)} clubs / {player_count} players "
            f"from {read_rows} rows ({kept_rows} retained)"
        )

    payload = {
        "year": start_year,
        "season": f"{start_year}/{str(start_year + 1)[-2:]}",
        "source": config["label"],
        "sourceUrl": config["url"],
        "exact": True,
        "clubCount": len(packed),
        "playerCount": player_count,
        "teams": packed,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{start_year}.json"
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    target.write_bytes(content)
    with gzip.open(f"{target}.gz", "wb", compresslevel=9) as archive:
        archive.write(content)
    print(f"Wrote {target.relative_to(ROOT)}: {len(packed)} clubs / {player_count} players", flush=True)


def main():
    for year, config in SOURCES.items():
        build_one(year, config)


if __name__ == "__main__":
    main()
