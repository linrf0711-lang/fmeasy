#!/usr/bin/env python3
"""Build compact, browser-friendly FMEASY squad files from public dataset mirrors."""

from __future__ import annotations

import csv
import difflib
import gzip
import hashlib
import io
import json
import re
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "squads"

HISTORICAL_URL = "https://raw.githubusercontent.com/lbenz730/fifa_model/master/player_stats.csv"

SOURCES = {
    **{
        year: {
            "url": HISTORICAL_URL,
            "label": f"Kaggle · FIFA {year + 1} Complete Player Dataset",
            "filter_year": year + 1,
        }
        for year in range(2004, 2016)
    },
    2016: {
        "url": "https://raw.githubusercontent.com/sumairrathore/Project_4/main/data/raw_data/players_17.csv",
        "label": "Kaggle · FIFA 17 Complete Player Dataset",
    },
    2017: {
        "url": "https://raw.githubusercontent.com/sumairrathore/Project_4/main/data/raw_data/players_18.csv",
        "label": "Kaggle · FIFA 18 Complete Player Dataset",
    },
    2018: {
        "url": "https://raw.githubusercontent.com/sumairrathore/Project_4/main/data/raw_data/players_19.csv",
        "label": "Kaggle · FIFA 19 Complete Player Dataset",
    },
    2019: {
        "url": "https://raw.githubusercontent.com/sumairrathore/Project_4/main/data/raw_data/players_20.csv",
        "label": "Kaggle · FIFA 20 Complete Player Dataset",
    },
    2020: {
        "url": "https://raw.githubusercontent.com/sumairrathore/Project_4/main/data/raw_data/players_21.csv",
        "label": "Kaggle · FIFA 21 Complete Player Dataset",
    },
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

TEXT_CACHE: dict[str, str] = {}

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

POSITION_ALIASES = {
    "GK": "GK", "G": "GK",
    "SW": "CB", "CB": "CB", "LCB": "CB", "RCB": "CB",
    "LB": "LB", "LWB": "LWB", "RB": "RB", "RWB": "RWB",
    "DM": "DM", "CDM": "DM", "LDM": "DM", "RDM": "DM",
    "LCDM": "DM", "RCDM": "DM",
    "CM": "CM", "LCM": "CM", "RCM": "CM",
    "AM": "AM", "CAM": "AM", "LAM": "AM", "RAM": "AM",
    "LCAM": "AM", "RCAM": "AM",
    "LM": "LM", "LWM": "LW", "RM": "RM", "RWM": "RW",
    "LW": "LW", "LF": "LW", "RW": "RW", "RF": "RW",
    "CF": "CF", "ST": "ST", "LS": "ST", "RS": "ST",
}

POSITION_RATING_COLUMNS = {
    "GK": ("gk",),
    "CB": ("cb", "lcb", "rcb"),
    "LB": ("lb",),
    "LWB": ("lwb",),
    "RB": ("rb",),
    "RWB": ("rwb",),
    "DM": ("cdm", "ldm", "rdm"),
    "CM": ("cm", "lcm", "rcm"),
    "AM": ("cam", "lam", "ram"),
    "LM": ("lm",),
    "RM": ("rm",),
    "LW": ("lw", "lf"),
    "RW": ("rw", "rf"),
    "CF": ("cf",),
    "ST": ("st", "ls", "rs"),
}

FIFA_ATTRIBUTE_ALIASES = {
    "pace": ("pace",), "shooting": ("shooting",), "passing": ("passing",),
    "dribbling": ("dribbling",), "defending": ("defending",), "physical": ("physic", "physical"),
    "acceleration": ("acceleration", "movement_acceleration"),
    "sprintSpeed": ("sprint_speed", "movement_sprint_speed"),
    "agility": ("agility", "movement_agility"), "balance": ("balance", "movement_balance"),
    "reactions": ("reactions", "movement_reactions"), "ballControl": ("ball_control", "skill_ball_control"),
    "composure": ("composure", "mentality_composure"), "crossing": ("crossing", "attacking_crossing"),
    "finishing": ("finishing", "attacking_finishing"),
    "headingAccuracy": ("heading_accuracy", "attacking_heading_accuracy"),
    "shortPassing": ("short_pass", "short_passing", "attacking_short_passing"),
    "volleys": ("volleys", "attacking_volleys"), "longPassing": ("long_pass", "long_passing", "skill_long_passing"),
    "curve": ("curve", "skill_curve"), "freeKickAccuracy": ("free_kick_accuracy", "skill_fk_accuracy"),
    "shotPower": ("shot_power", "power_shot_power"), "longShots": ("long_shots", "power_long_shots"),
    "interceptions": ("interceptions", "mentality_interceptions"),
    "positioning": ("att_position", "positioning", "mentality_positioning"),
    "vision": ("vision", "mentality_vision"), "penalties": ("penalties", "mentality_penalties"),
    "marking": ("marking", "defending_marking_awareness"),
    "standingTackle": ("stand_tackle", "standing_tackle", "defending_standing_tackle"),
    "slidingTackle": ("slide_tackle", "sliding_tackle", "defending_sliding_tackle"),
    "strength": ("strength", "power_strength"), "stamina": ("stamina", "power_stamina"),
    "jumping": ("jumping", "power_jumping"), "aggression": ("aggression", "mentality_aggression"),
    "gkDiving": ("gk_diving", "goalkeeping_diving"), "gkHandling": ("gk_handling", "goalkeeping_handling"),
    "gkKicking": ("gk_kicking", "goalkeeping_kicking"), "gkReflexes": ("gk_reflexes", "goalkeeping_reflexes"),
    "gkPositioning": ("gk_positioning", "goalkeeping_positioning"),
}

FAKE_NAME_PATTERNS = (
    r"^player\s*\d+$", r"^fake(?:\s+player)?", r"^generic(?:\s+player)?",
    r"^random(?:\s+player)?", r"^unnamed(?:\s+player)?", r"^dummy(?:\s+player)?",
    r"^unknown(?:\s+player)?", r"^unidentified(?:\s+player)?", r"^not\s+named",
    r"^(?:n/?a|none|null|tbd|-)$", r"^newgen", r"^资料待补", r"^未命名", r"^青训\s*\d+$",
)

LEAGUE_CSV = (
    "https://raw.githubusercontent.com/datasets/football-datasets/"
    "main/datasets/{slug}/season-{short}.csv"
)

LEAGUE_SPECS = {
    "Premier League": {"slug": "premier-league", "country": "England", "squadRoot": "eng", "squadLeague": "engprem"},
    "La Liga": {"slug": "la-liga", "country": "Spain", "squadRoot": "spain", "squadLeague": "laliga"},
    "Serie A": {"slug": "serie-a", "country": "Italy", "squadRoot": "italy", "squadLeague": "seriea"},
    "Bundesliga": {"slug": "bundesliga", "country": "Germany", "squadRoot": "ger", "squadLeague": "bundes"},
    "Ligue 1": {"slug": "ligue-1", "country": "France", "squadRoot": "france", "squadLeague": "ligue1"},
}

FOOTBALL_SQUADS_BASE = (
    "https://raw.githubusercontent.com/footballcsv/cache.footballsquads/master/"
    "{root}/{start}-{end}/{league}"
)

CLUB_ALIASES = {
    "man united": "manchester united", "man city": "manchester city",
    "tottenham": "tottenham hotspur", "spurs": "tottenham hotspur",
    "west brom": "west bromwich albion", "west bromwich": "west bromwich albion",
    "qpr": "queens park rangers", "nottm forest": "nottingham forest",
    "newcastle": "newcastle united", "wolves": "wolverhampton wanderers",
    "brighton": "brighton and hove albion", "leicester": "leicester city",
    "leeds": "leeds united", "west ham": "west ham united", "stoke": "stoke city",
    "swansea": "swansea city", "hull": "hull city", "norwich": "norwich city",
    "cardiff": "cardiff city", "huddersfield": "huddersfield town",
    "bournemouth": "afc bournemouth", "luton": "luton town", "ipswich": "ipswich town",
    "birmingham": "birmingham city", "wigan": "wigan athletic", "blackburn": "blackburn rovers",
    "derby": "derby county",
    "bolton": "bolton wanderers", "charlton": "charlton athletic", "sheffield utd": "sheffield united",
    # La Liga names used by the public season files.
    "ath madrid": "atletico madrid", "ath bilbao": "athletic de bilbao",
    "club atletico de madrid": "atletico madrid", "atletico de madrid": "atletico madrid",
    "espanol": "rcd espanyol", "la coruna": "rc deportivo la coruna",
    "rcd espanyol de barcelona": "rcd espanyol", "rc deportivo de la coruna": "rc deportivo la coruna",
    "betis": "real betis", "mallorca": "rcd mallorca", "santander": "racing santander",
    "real betis balompie": "real betis", "real club deportivo mallorca": "rcd mallorca",
    "sociedad": "real sociedad", "zaragoza": "real zaragoza", "alaves": "deportivo alaves",
    "real sociedad de futbol": "real sociedad", "celta": "rc celta",
    "real club celta de vigo": "rc celta", "rc celta vigo": "rc celta",
    "gimnastic": "tarragona", "club gimnastic": "tarragona",
    "gimnastic de tarragona": "tarragona", "recreativo": "rc recreativo",
    "sp gijon": "sporting gijon", "vallecano": "rayo vallecano", "huesca": "sd huesca",
    "rayo vallecano de madrid": "rayo vallecano", "real madrid club de futbol": "real madrid",
    "sevilla futbol club": "sevilla", "valencia club de futbol": "valencia",
    "oviedo": "real oviedo", "murcia": "real murcia",
    # Serie A names used by the public season files.
    "inter": "inter milan", "roma": "as roma", "chievо": "chievo verona",
    "chievo": "chievo verona", "fiorentina": "acf fiorentina",
    "sampdoria": "doria", "uc sampdoria": "doria", "fiorentina": "firenze",
    "acf fiorentina": "firenze", "genoa": "genova", "f genova": "genova",
    "verona": "hellas verona",
    "sassuolo": "us sassuolo calcio", "salernitana": "us salernitana 1919",
    # Bundesliga names used by the public season files.
    "dortmund": "borussia dortmund", "wolfsburg": "vfl wolfsburg",
    "hamburg": "hamburg", "hamburger sv": "hamburg", "hamburg sv": "hamburg",
    "hamburger sport verein": "hamburg", "cologne": "koln", "1 koln": "koln",
    "hertha": "hertha bsc", "bochum": "vfl bochum",
    "leverkusen": "bayer leverkusen", "bielefeld": "arminia bielefeld",
    "mgladbach": "borussia monchengladbach", "borussia m gladbach": "borussia monchengladbach",
    "monchengladbach": "borussia monchengladbach", "stuttgart": "vfb stuttgart",
    "duisburg": "msv duisburg", "koln": "1 koln", "ein frankfurt": "eintracht frankfurt",
    "aachen": "alemannia aachen", "cottbus": "energie cottbus",
    "nurnberg": "1 nurnberg", "karlsruhe": "karlsruher sc",
    "freiburg": "sc freiburg", "hoffenheim": "tsg hoffenheim",
    "darmstadt": "sv darmstadt 98", "paderborn": "sc paderborn 07",
    "1 fsv mainz 05": "mainz", "mainz 05": "mainz",
    # Ligue 1 names used by the public season files.
    "nice": "ogc nice", "lyon": "olympique lyonnais", "ol": "olympique lyonnais",
    "bastia": "sc bastia",
    "caen": "sm caen", "lille": "lille osc", "paris sg": "paris saint germain",
    "losc lille metropole": "lille osc", "lille osc metropole": "lille osc",
    "strasbourg": "rc strasbourg", "st etienne": "as saint etienne",
    "monaco": "as monaco", "lens": "rc lens", "nancy": "as nancy lorraine",
    "troyes": "es troyes", "marseille": "olympique de marseille", "om": "olympique de marseille",
    "bordeaux": "girondins bordeaux", "auxerre": "aj auxerre", "nantes": "nantes",
    "sochaux": "sochaux", "valenciennes": "valenciennes",
    "grenoble": "grenoble foot 38", "boulogne": "us boulogne",
    "arles": "arles avignon", "brest": "stade brestois 29", "dijon": "dijon fco",
    "reims": "stade de reims", "guingamp": "en avant guingamp", "rennes": "stade rennais",
    "angers": "angers sco", "amiens": "amiens sc", "nimes": "nimes olympique",
    "clermont": "clermont foot", "sedan": "cs sedan ardennes",
    "ajaccio gfco": "gfc ajaccio",
    "bergamo calcio": "atalanta", "latium": "lazio",
}


def fetch_text(url: str) -> str:
    if url in TEXT_CACHE:
        return TEXT_CACHE[url]
    request = urllib.request.Request(url, headers={"User-Agent": "FMEASY-squad-builder/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read()
    TEXT_CACHE[url] = raw.decode("utf-8-sig", errors="replace")
    return TEXT_CACHE[url]


def clean(value) -> str:
    return str(value or "").strip()


def clean_player_name(value: str) -> str:
    name = re.sub(r"\s+-\s*$", "", clean(value)).strip()
    # A few community mirrors prefix display names with a two-digit row/year marker.
    name = re.sub(r"^\d{2}[\s\u00a0]+(?=[A-Za-zÀ-ÖØ-öø-ÿ])", "", name).strip()
    return name


def is_fake_name(name: str) -> bool:
    value = clean(name).lower()
    return not value or any(re.search(pattern, value, re.I) for pattern in FAKE_NAME_PATTERNS)


def identity_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode().lower()
    value = value.replace("&", " and ").replace("'", "")
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    # Join punctuated initials (F.C. -> fc, R.C.D. -> rcd), then remove legal
    # company suffixes and common club-designator phrases without touching names.
    value = re.sub(r"\b(?:[a-z]\s+){1,4}[a-z]\b", lambda m: m.group().replace(" ", ""), value)
    value = re.sub(r"\b(?:s\s*a\s*d|sad)\b", " ", value)
    value = re.sub(r"\b(?:football club|futbol club|club de futbol)\b", " ", value)
    value = re.sub(r"\b(?:fc|afc|cf|ac)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return CLUB_ALIASES.get(value, value)


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(identity_key(part) for part in parts).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


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


def rating_number(value, default=None):
    match = re.search(r"-?\d+(?:\.\d+)?", clean(value).replace(",", ""))
    return number(match.group()) if match else default


def parse_positions(*values) -> list[str]:
    positions: list[str] = []
    for value in values:
        text = re.sub(r"<[^>]*>", " ", clean(value)).upper()
        for token in re.findall(r"[A-Z]{1,5}", text):
            position = POSITION_ALIASES.get(token)
            if position and position not in positions:
                positions.append(position)
    return positions


def infer_positions(row: dict[str, str]) -> list[str]:
    lowered = {str(key).strip().lower(): value for key, value in row.items() if key is not None}
    goalkeeper = [
        rating_number(first(row, name))
        for name in ("gk_diving", "goalkeeping_diving", "gk_handling", "goalkeeping_handling",
                     "gk_positioning", "goalkeeping_positioning", "gk_reflexes", "goalkeeping_reflexes")
    ]
    goalkeeper = [value for value in goalkeeper if value is not None]
    scored: list[tuple[float, str]] = []
    for position, columns in POSITION_RATING_COLUMNS.items():
        ratings = [rating_number(lowered.get(column)) for column in columns]
        ratings = [value for value in ratings if value is not None]
        if ratings:
            scored.append((max(ratings), position))
    if goalkeeper and sum(goalkeeper) / len(goalkeeper) >= 45 and (not scored or max(scored)[0] < 50):
        return ["GK"]
    if scored:
        scored.sort(reverse=True)
        best = scored[0][0]
        return [position for score, position in scored if score >= best - 4][:4]

    if goalkeeper and sum(goalkeeper) / len(goalkeeper) >= 45:
        return ["GK"]

    defense = [rating_number(first(row, name)) for name in
               ("marking", "defending_marking_awareness", "stand_tackle", "defending_standing_tackle",
                "slide_tackle", "defending_sliding_tackle", "interceptions")]
    midfield = [rating_number(first(row, name)) for name in
                ("short_pass", "attacking_short_passing", "long_pass", "skill_long_passing", "vision", "ball_control")]
    attack = [rating_number(first(row, name)) for name in
              ("finishing", "attacking_finishing", "att_position", "mentality_positioning", "dribbling")]
    averages = {
        "CB": sum(x for x in defense if x is not None) / max(1, sum(x is not None for x in defense)),
        "CM": sum(x for x in midfield if x is not None) / max(1, sum(x is not None for x in midfield)),
        "ST": sum(x for x in attack if x is not None) / max(1, sum(x is not None for x in attack)),
    }
    return [max(averages, key=averages.get)]


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


def fetch_league_teams(start_year: int, slug: str) -> tuple[list[str], str]:
    short = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
    url = LEAGUE_CSV.format(slug=slug, short=short)
    text = fetch_text(url)
    reader = csv.DictReader(io.StringIO(text))
    teams: list[str] = []
    for row in reader:
        for field in ("HomeTeam", "AwayTeam"):
            name = clean(row.get(field))
            if name and name not in teams:
                teams.append(name)
    if len(teams) < 16 or len(teams) > 22:
        raise RuntimeError(f"{slug} {start_year} team-list check failed: {len(teams)}")
    return teams, url


def match_club(source_name: str, available: dict[str, list[dict]]):
    wanted = identity_key(source_name)
    grouped: dict[str, list[str]] = defaultdict(list)
    for name in available:
        grouped[identity_key(name)].append(name)

    def best_variant(names: list[str]) -> str:
        return max(
            names,
            key=lambda name: (
                len(available.get(name, [])),
                sum(p.get("overall", 0) for p in available.get(name, [])[:18]),
                -len(name),
            ),
        )

    if wanted in grouped:
        return best_variant(grouped[wanted]), "normalized-exact"

    generic = {
        "real", "club", "football", "futbol", "de", "del", "la", "the",
        "fc", "cf", "ac", "afc", "rc", "rcd", "sd", "ud", "sc", "as",
        "us", "vfl", "vfb", "fsv", "tsg", "losc", "osc", "sm", "uc",
        "calcio", "balompie", "metropole", "sad", "sa",
    }
    wanted_tokens = {token for token in wanted.split() if token not in generic and len(token) > 2}
    contained = []
    for key, names in grouped.items():
        candidate_tokens = {token for token in key.split() if token not in generic and len(token) > 2}
        if wanted_tokens and wanted_tokens <= candidate_tokens:
            contained.extend(names)
    if contained:
        return best_variant(contained), "distinctive-token-match"
    ranked = sorted(
        ((difflib.SequenceMatcher(None, wanted, key).ratio(), key) for key in grouped),
        reverse=True,
    )
    if ranked and ranked[0][0] >= .82 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= .08):
        return best_variant(grouped[ranked[0][1]]), f"unambiguous-fuzzy-{ranked[0][0]:.2f}"
    return None, "unmatched"


def football_squads_index(start_year: int, spec: dict) -> tuple[str, dict[str, str]]:
    base = FOOTBALL_SQUADS_BASE.format(
        root=spec["squadRoot"], start=start_year, end=start_year + 1,
        league=spec["squadLeague"],
    )
    try:
        readme = fetch_text(f"{base}/README.md")
    except Exception:
        return base, {}
    return base, {
        clean(name): clean(path)
        for name, path in re.findall(r"^- \[([^]]+)\]\(([^)]+\.txt)\)", readme, re.M)
    }


def parse_football_squads(text: str, start_year: int, club: str, country: str) -> list[dict]:
    players = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row or row[0].lstrip().startswith("=") or len(row) < 7:
            if row and clean(row[0]).lower().startswith("== past players"):
                break
            continue
        name = clean_player_name(row[1] if len(row) > 1 else "")
        if is_fake_name(name) or name.lower() == "name":
            continue
        source_position = clean(row[3]).upper()
        position = {"G": "GK", "D": "CB", "M": "CM", "F": "ST"}.get(source_position)
        if not position:
            continue
        birth_raw = clean(row[6])
        birth_match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{2,4})", birth_raw)
        birth = None
        age = None
        if birth_match:
            day, month, year = map(int, birth_match.groups())
            if year < 100:
                year += 2000
                if year > start_year - 15:
                    year -= 100
            birth = f"{year:04d}-{month:02d}-{day:02d}"
            age = max(15, min(45, start_year - year))
        nationality = clean(row[2]) or None
        number_value = number(row[0])
        player = {
            "canonicalPlayerId": stable_id("player", name, birth or "", nationality or "", position),
            "fifaId": None,
            "pesId": None,
            "name": name,
            "fullName": name,
            "dateOfBirth": birth,
            "nationality": nationality,
            "sourcePos": source_position,
            "positions": [position],
            "registeredPosition": position,
            "playablePositions": [position],
            "primaryPosition": position,
            "secondaryPositions": [],
            "positionEstimated": True,
            "positionEstimationMethod": "FootballSquads coarse G/D/M/F registration group",
            "positionConfidence": "medium",
            "age": age if age is not None else 24,
            "ageEstimated": age is None,
            "role": "一线队",
            "registrationStatus": "registered",
            "source": "FootballSquads / footballcsv (CC0)",
            "fifaVersion": None,
            "fifaDataYear": None,
            "fifaSource": None,
            "fifaConfidence": None,
            "fifaAttributes": {},
            "pesVersion": None,
            "pesOverall": None,
            "pesRegisteredPosition": None,
            "pesPlayablePositions": [],
            "canonicalClubId": stable_id("club", club, country),
        }
        height = number(row[4])
        if height:
            player["heightCm"] = int(round(height * 100 if height < 3 else height))
        if number_value is not None and 0 < number_value < 100:
            player["number"] = int(number_value)
        players.append(player)
    deduped = {}
    for player in players:
        deduped.setdefault(player["canonicalPlayerId"], player)
    return list(deduped.values())


def supplement_real_rotation_players(
    start_year: int, spec: dict, source_name: str, data_name: str | None,
    packed: dict[str, list[dict]],
) -> tuple[str | None, int]:
    if start_year > 2023:
        return data_name, 0
    base, index = football_squads_index(start_year, spec)
    if not index:
        return data_name, 0
    index_as_teams = {name: [{}] for name in index}
    squad_name, _ = match_club(source_name, index_as_teams)
    if not squad_name:
        return data_name, 0
    try:
        squad = parse_football_squads(
            fetch_text(f"{base}/{index[squad_name]}"), start_year, squad_name, spec["country"]
        )
    except Exception:
        return data_name, 0
    if not squad:
        return data_name, 0
    target = data_name or squad_name
    current = packed.setdefault(target, [])
    known_ids = {p.get("canonicalPlayerId") for p in current}
    known_names = {identity_key(p.get("name", "")) for p in current}
    added = 0
    for player in squad:
        if player["canonicalPlayerId"] in known_ids or identity_key(player["name"]) in known_names:
            continue
        current.append(player)
        known_ids.add(player["canonicalPlayerId"])
        known_names.add(identity_key(player["name"]))
        added += 1
    return target, added


def normalize_player(row: dict[str, str], start_year: int, source: str):
    name = clean_player_name(first(row, "short_name", "name", "full_name", "long_name", "player_name"))
    club = first(row, "club_name", "club", "team_name", "team")
    league = first(row, "league_name", "club_league_name", "league", "competition")
    if is_fake_name(name) or not club or club.lower() in {"free agents", "free agent", "nan", "none"}:
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
    age_estimated = age is None
    if age is None:
        age = 24

    positions = parse_positions(
        first(row, "player_positions"),
        first(row, "preferred_positions"),
        first(row, "positions"),
        first(row, "preferredposition1"),
        first(row, "preferredposition2"),
        first(row, "preferredposition3"),
        first(row, "preferredposition4"),
        first(row, "club_position"),
        first(row, "position"),
    )
    position_estimated = not positions
    if position_estimated:
        positions = infer_positions(row)
    jersey = number(first(row, "club_jersey_number", "jersey_number", "number", "club_kit_number"))
    value = money_millions(first(row, "value_eur", "value", "market_value", "marketvalue"))
    loan_from = first(row, "club_loaned_from", "loaned_from", "loan_from")
    club_position = re.sub(r"<[^>]*>", " ", first(row, "club_position")).upper().strip()
    role = "后备／青年" if club_position in {"SUB", "RES", "U23", "U21", "U19"} else "一线队"

    source_player_id = first(row, "sofifa_id", "player_id", "playerid", "id")
    full_name = clean_player_name(first(row, "long_name", "full_name", "player_name")) or name
    canonical_id = (
        f"fifa-{source_player_id}" if source_player_id
        else stable_id(
            "player", full_name, birth,
            first(row, "nationality_name", "nationality", "country"), positions[0],
        )
    )
    attributes = {}
    for field, aliases in FIFA_ATTRIBUTE_ALIASES.items():
        value = rating_number(first(row, *aliases))
        if value is not None:
            attributes[field] = max(1, min(99, int(round(value))))
    player = {
        "canonicalPlayerId": canonical_id,
        "fifaId": source_player_id or None,
        "name": name,
        "fullName": full_name,
        "dateOfBirth": birth or None,
        "nationality": first(row, "nationality_name", "nationality", "country") or None,
        "heightCm": int(number(first(row, "height_cm", "height"))) if number(first(row, "height_cm", "height")) else None,
        "sourcePos": "/".join(positions[:4]),
        "positions": positions[:4],
        "registeredPosition": positions[0],
        "playablePositions": positions[:4],
        "primaryPosition": positions[0],
        "secondaryPositions": positions[1:4],
        "fifaRegisteredPosition": positions[0],
        "fifaPlayablePositions": positions[:4],
        "positionEstimated": position_estimated,
        "positionEstimationMethod": "highest FIFA positional rating within four points" if position_estimated else None,
        "positionConfidence": "medium" if position_estimated else "high",
        "age": max(15, min(45, int(round(age)))),
        "ageEstimated": age_estimated,
        "overall": max(40, min(99, int(round(overall)))),
        "potential": max(40, min(99, int(round(potential)))),
        "fifaVersion": first(row, "fifa_version", "year", "version") or f"FIFA {start_year + 1}",
        "fifaDataYear": start_year,
        "fifaSource": source,
        "fifaConfidence": "high",
        "fifaAttributes": attributes,
        "pesId": None,
        "pesVersion": None,
        "pesOverall": None,
        "pesRegisteredPosition": None,
        "pesPlayablePositions": [],
        "role": role,
        "source": source,
    }
    if jersey is not None and 0 < jersey < 100:
        player["number"] = int(jersey)
    if value is not None:
        player["marketValue"] = value
    if loan_from:
        player["loanFrom"] = loan_from
    stamina = rating_number(first(row, "stamina", "power_stamina"))
    if stamina is not None:
        player["stamina"] = max(1, min(99, int(round(stamina))))
    preferred_foot = first(row, "preferred_foot", "preferredfoot")
    if preferred_foot:
        player["preferredFoot"] = preferred_foot
    player["rawSource"] = {str(k): clean(v) for k, v in row.items() if k is not None and clean(v)}
    return club, source_player_id, player


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
    leagues = {}
    club_countries: dict[str, str] = {}
    premier_data_clubs: set[str] = set()
    for league_name, spec in LEAGUE_SPECS.items():
        season_teams, season_team_source = fetch_league_teams(start_year, spec["slug"])
        club_matches = []
        matched_clubs: set[str] = set()
        for source_name in season_teams:
            data_name, method = match_club(source_name, packed)
            supplemented = 0
            if not data_name or len(packed.get(data_name, [])) < 18:
                data_name, supplemented = supplement_real_rotation_players(
                    start_year, spec, source_name, data_name, packed
                )
                if supplemented:
                    method = f"{method}+football-squads"
            if data_name:
                matched_clubs.add(data_name)
                club_countries[data_name] = spec["country"]
            club_matches.append({
                "sourceName": source_name,
                "dataName": data_name,
                "canonicalClubId": stable_id("club", source_name, spec["country"]),
                "matchMethod": method,
                "playersFound": len(packed.get(data_name, [])) if data_name else 0,
                "rotationReady": len(packed.get(data_name, [])) >= 18 if data_name else False,
                "supplementedRealPlayers": supplemented,
            })
        if league_name == "Premier League":
            premier_data_clubs = matched_clubs
        leagues[league_name] = {
            "country": spec["country"],
            "seasonTeamSource": season_team_source,
            "clubsExpected": len(season_teams),
            "clubsFound": len(matched_clubs),
            "playersFound": sum(len(packed[name]) for name in matched_clubs),
            "clubsRotationReady": sum(len(packed[name]) >= 18 for name in matched_clubs),
            "clubs": club_matches,
            "confidence": "high" if len(matched_clubs) == len(season_teams) else "partial",
        }

    # Stage one preserves complete source rows for Premier League records only.
    # Other leagues remain compact so the existing browser loader stays fast.
    for club, players in packed.items():
        for player in players:
            player["canonicalClubId"] = stable_id("club", club, club_countries.get(club, ""))
            if club not in premier_data_clubs:
                player.pop("rawSource", None)

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
        "leagues": leagues,
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
