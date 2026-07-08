import json
import os

import storage

CURRENCY_NAME  = "YoranCoins"
CURRENCY_EMOJI = "🪙"

ECON_FILE = storage.path("economy.json")
SHOP_FILE = storage.path("shop.json")


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _save(path: str, data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _user(data: dict, guild_id: int, user_id: int) -> dict:
    g = data.setdefault(str(guild_id), {})
    return g.setdefault(str(user_id), {"balance": 0, "bank": 0, "job": None})


def get_balance(guild_id: int, user_id: int) -> int:
    data = _load(ECON_FILE)
    return data.get(str(guild_id), {}).get(str(user_id), {}).get("balance", 0)


def add_balance(guild_id: int, user_id: int, amount: int) -> int:
    data = _load(ECON_FILE)
    u = _user(data, guild_id, user_id)
    u["balance"] = max(0, u.get("balance", 0) + amount)
    _save(ECON_FILE, data)
    return u["balance"]


def get_bank(guild_id: int, user_id: int) -> int:
    data = _load(ECON_FILE)
    return data.get(str(guild_id), {}).get(str(user_id), {}).get("bank", 0)


def add_bank(guild_id: int, user_id: int, amount: int) -> int:
    data = _load(ECON_FILE)
    u = _user(data, guild_id, user_id)
    u["bank"] = max(0, u.get("bank", 0) + amount)
    _save(ECON_FILE, data)
    return u["bank"]


def get_job(guild_id: int, user_id: int) -> str | None:
    data = _load(ECON_FILE)
    return data.get(str(guild_id), {}).get(str(user_id), {}).get("job")


def set_job(guild_id: int, user_id: int, job: str | None):
    data = _load(ECON_FILE)
    u = _user(data, guild_id, user_id)
    u["job"] = job
    _save(ECON_FILE, data)


def set_cooldown(guild_id: int, user_id: int, key: str, timestamp: float):
    data = _load(ECON_FILE)
    u = _user(data, guild_id, user_id)
    u[key] = timestamp
    _save(ECON_FILE, data)


def get_cooldown(guild_id: int, user_id: int, key: str) -> float:
    data = _load(ECON_FILE)
    return data.get(str(guild_id), {}).get(str(user_id), {}).get(key, 0)


def get_leaderboard(guild_id: int, limit: int = 10) -> list[tuple[str, int, int]]:
    """Returns [(user_id, wallet, bank), ...] sorted by net worth (wallet + bank) descending."""
    data = _load(ECON_FILE).get(str(guild_id), {})
    ranked = sorted(data.items(), key=lambda kv: kv[1].get("balance", 0) + kv[1].get("bank", 0), reverse=True)
    return [(uid, u.get("balance", 0), u.get("bank", 0)) for uid, u in ranked[:limit]]


def get_shop_items(guild_id: int) -> list[dict]:
    data = _load(SHOP_FILE)
    return data.get(str(guild_id), [])


def add_shop_item(guild_id: int, name: str, price: int, role_id: int):
    data = _load(SHOP_FILE)
    items = data.setdefault(str(guild_id), [])
    items.append({"name": name, "price": price, "role_id": role_id})
    _save(SHOP_FILE, data)


def remove_shop_item(guild_id: int, name: str) -> bool:
    data = _load(SHOP_FILE)
    items = data.get(str(guild_id), [])
    for item in items:
        if item["name"].lower() == name.lower():
            items.remove(item)
            _save(SHOP_FILE, data)
            return True
    return False
