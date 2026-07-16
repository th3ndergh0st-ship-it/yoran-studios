import json
import os

import storage

SETTINGS_FILE = storage.path("settings.json")

DEFAULTS = {
    "economy": {
        "daily_min": 50,
        "daily_max": 120,
        "daily_cooldown": 86400,
        "work_min": 25,
        "work_max": 75,
        "work_cooldown": 3600,
        "beg_min": 5,
        "beg_max": 20,
        "beg_cooldown": 900,
        "beg_nothing_chance": 0.15,
        "crime_cooldown": 1800,
        "crime_success_chance": 0.6,
        "crime_win_min": 60,
        "crime_win_max": 160,
        "crime_fail_min": 75,
        "crime_fail_max": 225,
        "rob_cooldown": 7200,
        "rob_success_chance": 0.40,
        "rob_min_target_balance": 50,
        "rob_steal_pct_min": 0.10,
        "rob_steal_pct_max": 0.35,
        "rob_fine_pct_min": 0.10,
        "rob_fine_pct_max": 0.30,
        "rob_fine_min": 50,
        "gamble_cooldown": 15,
    },
    "levels": {
        "xp_min": 15,
        "xp_max": 25,
        "xp_cooldown": 60,
    },
    "trivia": {
        "cooldown": 300,
        "reward_min": 10,
        "reward_max": 25,
    },
    "counting": {
        "milestone_every": 50,
        "milestone_reward": 50,
    },
}

FIELD_TYPES = {}
for _section, _values in DEFAULTS.items():
    for _key, _val in _values.items():
        FIELD_TYPES[f"{_section}.{_key}"] = type(_val)

_cache = None


def _read() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load() -> dict:
    global _cache
    stored = _read()
    merged = {}
    for section, values in DEFAULTS.items():
        merged[section] = {**values, **stored.get(section, {})}
    _cache = merged
    return merged


def all_settings() -> dict:
    return load()


def get(section: str, key: str):
    if _cache is None:
        load()
    return _cache.get(section, {}).get(key, DEFAULTS.get(section, {}).get(key))


def save(new_values: dict) -> dict:
    current = load()
    for section, values in new_values.items():
        if section not in DEFAULTS:
            continue
        for key, raw in values.items():
            if key not in DEFAULTS[section]:
                continue
            expected = FIELD_TYPES[f"{section}.{key}"]
            try:
                value = expected(raw)
            except (TypeError, ValueError):
                continue
            if expected is float:
                value = max(0.0, min(1.0, value)) if key.endswith(("_chance", "_pct_min", "_pct_max")) else max(0.0, value)
            elif expected is int:
                value = max(0, value)
            current[section][key] = value

    _validate(current)
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return load()


def _validate(cfg: dict):
    pairs = [
        ("economy", "daily_min", "daily_max"),
        ("economy", "work_min", "work_max"),
        ("economy", "beg_min", "beg_max"),
        ("economy", "crime_win_min", "crime_win_max"),
        ("economy", "crime_fail_min", "crime_fail_max"),
        ("economy", "rob_steal_pct_min", "rob_steal_pct_max"),
        ("economy", "rob_fine_pct_min", "rob_fine_pct_max"),
        ("levels", "xp_min", "xp_max"),
        ("trivia", "reward_min", "reward_max"),
    ]
    for section, low_key, high_key in pairs:
        low, high = cfg[section][low_key], cfg[section][high_key]
        if low > high:
            cfg[section][low_key], cfg[section][high_key] = high, low
