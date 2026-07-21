import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import aiohttp
import discord
from aiohttp import web

import settings
import storage
import economy_data as econ

CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
BASE_URL = os.getenv("DASHBOARD_URL", "").rstrip("/")

STUDIOS_GUILD_ID = 1523445628204482620
DEV_ROLE_ID = 1523445699377627186
ALWAYS_ALLOWED_USER_IDS = {1230234714229444623}

MAX_IMAGE_BYTES = 8_000_000
MAX_UPLOAD = 12 * 1024 * 1024

SESSION_TTL = 7 * 86400
COOKIE_NAME = "yoran_session"

API_BASE = "https://discord.com/api/v10"


def _sign(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _unsign(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data


def _redirect_uri(request: web.Request) -> str:
    if BASE_URL:
        return f"{BASE_URL}/callback"
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    return f"{scheme}://{request.host}/callback"


def _is_authorized(bot: discord.Client, user_id: int) -> bool:
    if user_id in ALWAYS_ALLOWED_USER_IDS:
        return True
    guild = bot.get_guild(STUDIOS_GUILD_ID)
    if guild is None:
        return False
    if guild.owner_id == user_id:
        return True
    member = guild.get_member(user_id)
    return bool(member and any(r.id == DEV_ROLE_ID for r in member.roles))


def _session(request: web.Request) -> dict | None:
    return _unsign(request.cookies.get(COOKIE_NAME, ""))


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPRequestEntityTooLarge:
        return web.json_response(
            {"error": f"That file is too large. Keep images under {MAX_IMAGE_BYTES // 1_000_000} MB."},
            status=413,
        )
    except web.HTTPException:
        raise
    except json.JSONDecodeError:
        return web.json_response({"error": "Malformed request."}, status=400)
    except Exception as e:
        print(f"[Dashboard] Unhandled error on {request.method} {request.path}: {e!r}", flush=True)
        if request.path.startswith("/api/"):
            return web.json_response({"error": f"Server error: {type(e).__name__}"}, status=500)
        raise


@web.middleware
async def auth_middleware(request: web.Request, handler):
    public = {"/login", "/callback", "/health"}
    if request.path in public:
        return await handler(request)

    sess = _session(request)
    bot = request.app["bot"]
    if sess is None:
        if request.path.startswith("/api/"):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.Response(text=_login_page(), content_type="text/html")

    uid = int(sess["uid"])
    if not _is_authorized(bot, uid):
        if request.path.startswith("/api/"):
            return web.json_response({"error": "forbidden"}, status=403)
        return web.Response(text=_denied_page(sess.get("name", "you")), content_type="text/html", status=403)

    request["user_id"] = uid
    request["user_name"] = sess.get("name", "")
    request["user_avatar"] = sess.get("avatar", "")
    return await handler(request)


async def handle_login(request: web.Request):
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }
    resp = web.HTTPFound(f"https://discord.com/oauth2/authorize?{urlencode(params)}")
    resp.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="Lax", secure=True)
    return resp


async def handle_callback(request: web.Request):
    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state or state != request.cookies.get("oauth_state"):
        return web.Response(text=_error_page("Invalid login attempt. Try again."), content_type="text/html", status=400)

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(request),
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE}/oauth2/token", data=data) as r:
            if r.status != 200:
                return web.Response(text=_error_page("Discord rejected the login."), content_type="text/html", status=400)
            token = (await r.json())["access_token"]
        async with session.get(f"{API_BASE}/users/@me", headers={"Authorization": f"Bearer {token}"}) as r:
            if r.status != 200:
                return web.Response(text=_error_page("Could not read your Discord profile."), content_type="text/html", status=400)
            user = await r.json()

    payload = {
        "uid": user["id"],
        "name": user.get("global_name") or user["username"],
        "avatar": f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png" if user.get("avatar") else "",
        "exp": time.time() + SESSION_TTL,
    }
    resp = web.HTTPFound("/")
    resp.set_cookie(COOKIE_NAME, _sign(payload), max_age=SESSION_TTL, httponly=True, samesite="Lax", secure=True)
    resp.del_cookie("oauth_state")
    return resp


async def handle_logout(request: web.Request):
    resp = web.HTTPFound("/")
    resp.del_cookie(COOKIE_NAME)
    return resp


async def handle_health(request: web.Request):
    return web.Response(text="Yoran (Yoran Studios) is online.")


async def handle_index(request: web.Request):
    return web.Response(text=_dashboard_page(request["user_name"], request["user_avatar"]), content_type="text/html")


async def api_stats(request: web.Request):
    bot = request.app["bot"]
    guild = bot.get_guild(STUDIOS_GUILD_ID)
    econ_data = econ._load(econ.ECON_FILE).get(str(STUDIOS_GUILD_ID), {})
    coins = sum(u.get("balance", 0) + u.get("bank", 0) for u in econ_data.values())

    from cogs.levels import get_guild_stats
    stats = get_guild_stats(STUDIOS_GUILD_ID)
    messages = sum(u.get("messages", 0) for u in stats.values())

    payload = {
        "bot": str(bot.user),
        "latency_ms": round(bot.latency * 1000),
        "guilds": len(bot.guilds),
        "commands": len(bot.tree.get_commands()),
        "members": guild.member_count if guild else 0,
        "humans": sum(1 for m in guild.members if not m.bot) if guild else 0,
        "roles": len(guild.roles) if guild else 0,
        "channels": len(guild.channels) if guild else 0,
        "economy_users": len(econ_data),
        "coins_circulating": coins,
        "tracked_messages": messages,
        "ranked_users": len(stats),
    }
    if guild:
        og = discord.utils.get(guild.roles, name="OG")
        vip = guild.get_role(1526499976421703731)
        follower = guild.get_role(1526375014876713142)
        payload["og"] = len(og.members) if og else 0
        payload["vip"] = len(vip.members) if vip else 0
        payload["followers"] = len(follower.members) if follower else 0
    return web.json_response(payload)


async def api_leaderboards(request: web.Request):
    bot = request.app["bot"]
    guild = bot.get_guild(STUDIOS_GUILD_ID)

    def name_of(uid: str) -> str:
        m = guild.get_member(int(uid)) if guild else None
        return m.display_name if m else f"({uid})"

    from cogs.levels import get_guild_stats
    from cogs.invites import get_invite_counts

    stats = get_guild_stats(STUDIOS_GUILD_ID)
    coins = [
        {"name": name_of(uid), "value": w + b}
        for uid, w, b in econ.get_leaderboard(STUDIOS_GUILD_ID, 10)
    ]
    levels = [
        {"name": name_of(uid), "value": u.get("level", 0), "extra": f"{u.get('xp', 0):,} xp"}
        for uid, u in sorted(stats.items(), key=lambda kv: (kv[1].get("level", 0), kv[1].get("xp", 0)), reverse=True)[:10]
    ]
    messages = [
        {"name": name_of(uid), "value": u.get("messages", 0)}
        for uid, u in sorted(stats.items(), key=lambda kv: kv[1].get("messages", 0), reverse=True)[:10]
    ]
    invites = [
        {"name": name_of(uid), "value": c}
        for uid, c in sorted(get_invite_counts(STUDIOS_GUILD_ID).items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]
    return web.json_response({"coins": coins, "levels": levels, "messages": messages, "invites": invites})


async def api_settings_get(request: web.Request):
    return web.json_response(settings.all_settings())


async def api_settings_post(request: web.Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    updated = settings.save(body)
    _log(request, "updated settings")
    if "presence" in body:
        await apply_presence(request.app["bot"])
    return web.json_response(updated)


def _log(request: web.Request, action: str):
    print(f"[Dashboard] {request['user_name']} ({request['user_id']}) {action}", flush=True)


def _decode_image(data_uri: str) -> bytes | None:
    if not data_uri or "," not in data_uri:
        return None
    try:
        raw = base64.b64decode(data_uri.split(",", 1)[1])
    except (ValueError, TypeError):
        return None
    return raw if 0 < len(raw) <= MAX_IMAGE_BYTES else None


async def apply_presence(bot: discord.Client):
    cfg = settings.all_settings()["presence"]
    types = {
        "playing": discord.ActivityType.playing,
        "watching": discord.ActivityType.watching,
        "listening": discord.ActivityType.listening,
        "competing": discord.ActivityType.competing,
    }
    statuses = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    await bot.change_presence(
        activity=discord.Activity(
            type=types.get(cfg["activity_type"], discord.ActivityType.watching),
            name=cfg["activity_name"] or "Yoran Studios",
        ),
        status=statuses.get(cfg["status"], discord.Status.online),
    )


async def api_bot_get(request: web.Request):
    bot = request.app["bot"]
    cfg = settings.all_settings()["presence"]
    return web.json_response({
        "username": bot.user.name,
        "avatar": str(bot.user.display_avatar.url),
        "id": str(bot.user.id),
        "presence": cfg,
        "status_options": list(settings.PRESENCE_STATUS),
        "type_options": list(settings.PRESENCE_TYPES),
    })


async def api_bot_post(request: web.Request):
    bot = request.app["bot"]
    body = await request.json()
    changes = {}

    username = (body.get("username") or "").strip()
    if username and username != bot.user.name:
        if not 2 <= len(username) <= 32:
            return web.json_response({"error": "Username must be 2-32 characters."}, status=400)
        changes["username"] = username

    avatar = _decode_image(body.get("avatar", ""))
    if body.get("avatar") and avatar is None:
        return web.json_response({"error": "Invalid image, or larger than 8 MB."}, status=400)
    if avatar:
        changes["avatar"] = avatar

    if changes:
        try:
            await bot.user.edit(**changes)
        except ValueError:
            return web.json_response(
                {"error": "Unsupported image format. Use PNG, JPG or GIF."}, status=400
            )
        except discord.HTTPException as e:
            msg = str(e)
            if e.status == 429 or "rate" in msg.lower():
                msg = "Discord rate limit — bot usernames can only change twice per hour. Try again later."
            elif e.status == 400 and "avatar" in msg.lower():
                msg = "Discord rejected that image. Try a smaller PNG or JPG."
            return web.json_response({"error": msg}, status=400)
        _log(request, f"changed bot {', '.join(changes)}")

    if "presence" in body:
        settings.save({"presence": body["presence"]})
        await apply_presence(bot)
        _log(request, "changed bot presence")

    return await api_bot_get(request)


async def api_guild_get(request: web.Request):
    guild = request.app["bot"].get_guild(STUDIOS_GUILD_ID)
    if guild is None:
        return web.json_response({"error": "guild unavailable"}, status=503)
    return web.json_response({
        "name": guild.name,
        "icon": str(guild.icon.url) if guild.icon else "",
        "members": guild.member_count,
    })


async def api_guild_post(request: web.Request):
    guild = request.app["bot"].get_guild(STUDIOS_GUILD_ID)
    if guild is None:
        return web.json_response({"error": "guild unavailable"}, status=503)
    body = await request.json()
    changes = {}

    name = (body.get("name") or "").strip()
    if name and name != guild.name:
        if not 2 <= len(name) <= 100:
            return web.json_response({"error": "Server name must be 2-100 characters."}, status=400)
        changes["name"] = name

    icon = _decode_image(body.get("icon", ""))
    if body.get("icon") and icon is None:
        return web.json_response({"error": "Invalid image, or larger than 8 MB."}, status=400)
    if icon:
        changes["icon"] = icon

    if changes:
        try:
            await guild.edit(reason=f"Dashboard edit by {request['user_name']}", **changes)
        except ValueError:
            return web.json_response(
                {"error": "Unsupported image format. Use PNG, JPG or GIF."}, status=400
            )
        except discord.HTTPException as e:
            msg = str(e)
            if e.status == 403:
                msg = "I don't have permission to edit this server."
            return web.json_response({"error": msg}, status=400)
        _log(request, f"changed server {', '.join(changes)}")
    return await api_guild_get(request)


async def api_channels(request: web.Request):
    guild = request.app["bot"].get_guild(STUDIOS_GUILD_ID)
    if guild is None:
        return web.json_response([])
    return web.json_response([
        {"id": str(c.id), "name": c.name}
        for c in sorted(guild.text_channels, key=lambda c: c.position)
    ])


async def api_roles(request: web.Request):
    guild = request.app["bot"].get_guild(STUDIOS_GUILD_ID)
    if guild is None:
        return web.json_response([])
    return web.json_response([
        {"id": str(r.id), "name": r.name}
        for r in sorted(guild.roles, key=lambda r: -r.position)
        if not r.is_default() and not r.managed
    ])


async def api_games_get(request: web.Request):
    from cogs.games import _load, _guild_games, STATUS_CHOICES
    games = _guild_games(_load(), STUDIOS_GUILD_ID)
    return web.json_response({
        "games": [{"id": gid, **g} for gid, g in games.items()],
        "status_options": STATUS_CHOICES,
    })


async def api_games_post(request: web.Request):
    from cogs.games import _load, _save, _slug, STATUS_CHOICES
    bot = request.app["bot"]
    guild = bot.get_guild(STUDIOS_GUILD_ID)
    if guild is None:
        return web.json_response({"error": "guild unavailable"}, status=503)

    body = await request.json()
    name = (body.get("name") or "").strip()
    status = body.get("status")
    description = (body.get("description") or "").strip()
    if not name or not description:
        return web.json_response({"error": "Name and description are required."}, status=400)
    if status not in STATUS_CHOICES:
        return web.json_response({"error": "Invalid status."}, status=400)

    data = _load()
    games = data.setdefault(str(STUDIOS_GUILD_ID), {})
    gid = _slug(name)
    if gid in games:
        return web.json_response({"error": f"A game named {name} already exists."}, status=400)

    try:
        role = await guild.create_role(name=f"🔔 {name}", mentionable=True,
                                       reason=f"Game added from dashboard by {request['user_name']}")
    except discord.HTTPException as e:
        return web.json_response({"error": str(e)}, status=400)

    games[gid] = {
        "name": name,
        "status": status,
        "description": description,
        "image_url": (body.get("image_url") or "").strip() or None,
        "role_id": role.id,
    }
    _save(data)
    _log(request, f"added game {name}")
    return await api_games_get(request)


async def api_games_delete(request: web.Request):
    from cogs.games import _load, _save, _guild_games
    guild = request.app["bot"].get_guild(STUDIOS_GUILD_ID)
    gid = request.match_info["gid"]
    data = _load()
    games = _guild_games(data, STUDIOS_GUILD_ID)
    info = games.pop(gid, None)
    if info is None:
        return web.json_response({"error": "Game not found."}, status=404)
    _save(data)
    if guild:
        role = guild.get_role(info.get("role_id"))
        if role:
            try:
                await role.delete(reason=f"Game removed from dashboard by {request['user_name']}")
            except discord.HTTPException:
                pass
    _log(request, f"removed game {info['name']}")
    return await api_games_get(request)


async def api_shop_get(request: web.Request):
    guild = request.app["bot"].get_guild(STUDIOS_GUILD_ID)
    items = []
    for item in econ.get_shop_items(STUDIOS_GUILD_ID):
        role = guild.get_role(item["role_id"]) if guild else None
        items.append({**item, "role_name": role.name if role else "(deleted role)"})
    return web.json_response(items)


async def api_shop_post(request: web.Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    try:
        price = int(body.get("price", 0))
        role_id = int(body.get("role_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid price or role."}, status=400)
    if not name or price <= 0 or not role_id:
        return web.json_response({"error": "Name, a positive price and a role are required."}, status=400)
    if any(i["name"].lower() == name.lower() for i in econ.get_shop_items(STUDIOS_GUILD_ID)):
        return web.json_response({"error": "An item with that name already exists."}, status=400)
    econ.add_shop_item(STUDIOS_GUILD_ID, name, price, role_id)
    _log(request, f"added shop item {name}")
    return await api_shop_get(request)


async def api_shop_delete(request: web.Request):
    name = request.match_info["name"]
    if not econ.remove_shop_item(STUDIOS_GUILD_ID, name):
        return web.json_response({"error": "Item not found."}, status=404)
    _log(request, f"removed shop item {name}")
    return await api_shop_get(request)


async def api_members(request: web.Request):
    guild = request.app["bot"].get_guild(STUDIOS_GUILD_ID)
    if guild is None:
        return web.json_response([])
    q = request.query.get("q", "").lower().strip()
    out = []
    for m in guild.members:
        if m.bot:
            continue
        if q and q not in m.display_name.lower() and q not in m.name.lower() and q != str(m.id):
            continue
        out.append({
            "id": str(m.id),
            "name": m.display_name,
            "avatar": str(m.display_avatar.url),
            "wallet": econ.get_balance(STUDIOS_GUILD_ID, m.id),
            "bank": econ.get_bank(STUDIOS_GUILD_ID, m.id),
        })
        if len(out) >= 25:
            break
    out.sort(key=lambda x: x["wallet"] + x["bank"], reverse=True)
    return web.json_response(out)


async def api_economy_give(request: web.Request):
    body = await request.json()
    try:
        uid = int(body.get("user_id"))
        amount = int(body.get("amount"))
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid member or amount."}, status=400)
    if amount == 0:
        return web.json_response({"error": "Amount can't be zero."}, status=400)

    if amount > 0:
        econ.add_balance(STUDIOS_GUILD_ID, uid, amount)
    else:
        take = -amount
        wallet = econ.get_balance(STUDIOS_GUILD_ID, uid)
        from_wallet = min(take, wallet)
        if from_wallet:
            econ.add_balance(STUDIOS_GUILD_ID, uid, -from_wallet)
        rest = take - from_wallet
        if rest:
            econ.add_bank(STUDIOS_GUILD_ID, uid, -rest)
    _log(request, f"{'gave' if amount > 0 else 'removed'} {abs(amount)} coins {'to' if amount > 0 else 'from'} {uid}")
    return web.json_response({
        "wallet": econ.get_balance(STUDIOS_GUILD_ID, uid),
        "bank": econ.get_bank(STUDIOS_GUILD_ID, uid),
    })


async def api_announce(request: web.Request):
    bot = request.app["bot"]
    guild = bot.get_guild(STUDIOS_GUILD_ID)
    body = await request.json()
    channel = guild.get_channel(int(body.get("channel_id", 0))) if guild else None
    if channel is None:
        return web.json_response({"error": "Pick a valid channel."}, status=400)

    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    if not description:
        return web.json_response({"error": "The message body is required."}, status=400)

    try:
        color = int((body.get("color") or "7B2FBE").lstrip("#"), 16)
    except ValueError:
        color = 0x7B2FBE

    embed = discord.Embed(title=title or None, description=description, color=color)
    image = (body.get("image_url") or "").strip()
    if image.startswith("http"):
        embed.set_image(url=image)
    embed.set_footer(text=f"{guild.name}  •  Announced by {request['user_name']}",
                     icon_url=guild.icon.url if guild.icon else None)
    embed.timestamp = discord.utils.utcnow()

    content = None
    ping = body.get("ping_role_id")
    if ping:
        role = guild.get_role(int(ping))
        if role:
            content = role.mention

    try:
        await channel.send(content=content, embed=embed)
    except discord.HTTPException as e:
        return web.json_response({"error": str(e)}, status=400)
    _log(request, f"announced in #{channel.name}")
    return web.json_response({"ok": True, "channel": channel.name})


async def api_config_get(request: web.Request):
    from cogs.logs import _load as load_logs
    from cogs.tickets import _load as load_tickets
    from cogs.counting import _load as load_counting
    from cogs.membercount import _load as load_count
    from cogs.verifysub import _load as load_vs, CONFIG_FILE

    gid = str(STUDIOS_GUILD_ID)
    logs = load_logs().get(gid, {})
    tickets = load_tickets().get(gid, {})
    counting = load_counting().get(gid, {})
    vs = load_vs(CONFIG_FILE).get(gid, {})
    return web.json_response({
        "ban_logs": str(logs.get("ban", "")),
        "mod_logs": str(logs.get("mod", "")),
        "action_logs": str(logs.get("action", "")),
        "automod_logs": str(logs.get("automod", "")),
        "ticket_logs": str(tickets.get("logs_channel_id", "")),
        "ticket_transcripts": str(tickets.get("transcripts_channel_id", "")),
        "counting_channel": str(counting.get("channel_id", "")),
        "membercount_channel": str(load_count().get(gid, "")),
        "verifysub_submit": str(vs.get("submit", "")),
        "verifysub_review": str(vs.get("review", "")),
        "counting_current": counting.get("current", 0),
        "counting_high": counting.get("high_score", 0),
    })


async def api_config_post(request: web.Request):
    from cogs.logs import _load as load_logs, LOGS_FILE
    from cogs.tickets import _load as load_tickets, _save as save_tickets
    from cogs.counting import _load as load_counting, _save as save_counting
    from cogs.membercount import _load as load_count, COUNT_FILE
    import json as _json

    body = await request.json()
    gid = str(STUDIOS_GUILD_ID)

    def as_id(key):
        raw = body.get(key)
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None

    logs = load_logs()
    lcfg = logs.setdefault(gid, {})
    for field, key in [("ban_logs", "ban"), ("mod_logs", "mod"), ("action_logs", "action"), ("automod_logs", "automod")]:
        if field in body:
            val = as_id(field)
            if val:
                lcfg[key] = val
            else:
                lcfg.pop(key, None)
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(LOGS_FILE, "w") as f:
        _json.dump(logs, f, indent=2)

    tickets = load_tickets()
    tcfg = tickets.setdefault(gid, {})
    for field, key in [("ticket_logs", "logs_channel_id"), ("ticket_transcripts", "transcripts_channel_id")]:
        if field in body:
            val = as_id(field)
            if val:
                tcfg[key] = val
            else:
                tcfg.pop(key, None)
    save_tickets(tickets)

    if "counting_channel" in body:
        counting = load_counting()
        ccfg = counting.setdefault(gid, {"current": 0, "high_score": 0, "last_user_id": None})
        val = as_id("counting_channel")
        if val:
            ccfg["channel_id"] = val
        save_counting(counting)

    if "membercount_channel" in body:
        counts = load_count()
        val = as_id("membercount_channel")
        if val:
            counts[gid] = val
        else:
            counts.pop(gid, None)
        with open(COUNT_FILE, "w") as f:
            _json.dump(counts, f, indent=2)

    _log(request, "updated channel config")
    return await api_config_get(request)


def _shell(body: str, extra_css: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yoran Studios — Bot Dashboard</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background:#0f0f1a; color:#e6e6f0; font-family:'Segoe UI',system-ui,sans-serif; line-height:1.6; }}
a {{ color:#a855f7; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:24px 20px 60px; }}
.center {{ min-height:100vh; display:flex; align-items:center; justify-content:center; text-align:center; padding:20px; }}
.card {{ background:#1a1a2e; border:1px solid #2a2a4a; border-radius:14px; padding:28px; }}
.btn {{ display:inline-block; background:#7B2FBE; color:#fff; border:0; border-radius:10px;
  padding:12px 22px; font-size:15px; font-weight:600; cursor:pointer; text-decoration:none; }}
.btn:hover {{ background:#8f3fd6; }}
.btn.ghost {{ background:transparent; border:1px solid #3a3a5a; color:#b9b9cc; }}
h1 {{ font-size:24px; }} h2 {{ font-size:18px; margin-bottom:14px; color:#c4b5fd; }}
{extra_css}
</style></head><body>{body}</body></html>"""


def _login_page() -> str:
    return _shell("""<div class="center"><div class="card" style="max-width:420px">
<div style="font-size:44px">🤖</div>
<h1 style="margin:8px 0 6px">Yoran Studios</h1>
<p style="color:#8b8ba7;margin-bottom:22px">Bot control panel</p>
<a class="btn" href="/login">Sign in with Discord</a>
<p style="color:#5c5c7a;font-size:13px;margin-top:18px">Access is restricted to the server owner and dev team.</p>
</div></div>""")


def _denied_page(name: str) -> str:
    return _shell(f"""<div class="center"><div class="card" style="max-width:420px">
<div style="font-size:44px">🚫</div>
<h1 style="margin:8px 0 6px">Access denied</h1>
<p style="color:#8b8ba7;margin-bottom:22px">Signed in as <b>{name}</b>, but this panel is limited to
the server owner and members with the dev role.</p>
<a class="btn ghost" href="/logout">Sign out</a>
</div></div>""")


def _error_page(msg: str) -> str:
    return _shell(f"""<div class="center"><div class="card" style="max-width:420px">
<div style="font-size:44px">⚠️</div><h1 style="margin:8px 0 6px">Something went wrong</h1>
<p style="color:#8b8ba7;margin-bottom:22px">{msg}</p>
<a class="btn" href="/">Back</a></div></div>""")


def _dashboard_page(name: str, avatar: str) -> str:
    css = """
header { display:flex; align-items:center; justify-content:space-between; gap:16px;
  padding-bottom:18px; border-bottom:1px solid #2a2a4a; margin-bottom:22px; flex-wrap:wrap; }
.who { display:flex; align-items:center; gap:10px; color:#b9b9cc; font-size:14px; }
.who img { width:34px; height:34px; border-radius:50%; }
nav { display:flex; gap:8px; margin-bottom:22px; flex-wrap:wrap; }
nav button { background:#1a1a2e; border:1px solid #2a2a4a; color:#b9b9cc; border-radius:10px;
  padding:9px 16px; font-size:14px; cursor:pointer; }
nav button.on { background:#7B2FBE; border-color:#7B2FBE; color:#fff; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:22px; }
.stat { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:16px; }
.stat .k { color:#8b8ba7; font-size:12px; text-transform:uppercase; letter-spacing:.6px; }
.stat .v { font-size:26px; font-weight:700; margin-top:4px; }
.cols { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; align-items:start; }
table { width:100%; border-collapse:collapse; font-size:14px; }
td { padding:7px 4px; border-bottom:1px solid #23233d; vertical-align:middle; }
td:last-child { text-align:right; color:#c4b5fd; font-variant-numeric:tabular-nums; }
.pos { color:#6b6b8a; width:28px; }
.set { display:grid; grid-template-columns:1fr 110px; gap:10px; align-items:center;
  padding:7px 0; border-bottom:1px solid #23233d; }
.set label { font-size:14px; color:#c9c9dd; }
.set small { display:block; color:#6b6b8a; font-size:11px; }
input, select, textarea { background:#0f0f1a; border:1px solid #3a3a5a; border-radius:8px; color:#e6e6f0;
  padding:8px 10px; font-size:14px; width:100%; font-family:inherit; }
.set input { text-align:right; }
input:focus, select:focus, textarea:focus { outline:0; border-color:#7B2FBE; }
textarea { resize:vertical; min-height:90px; }
.field { margin-bottom:12px; }
.field label { display:block; font-size:13px; color:#8b8ba7; margin-bottom:5px; }
.row { display:flex; gap:10px; flex-wrap:wrap; }
.row > * { flex:1; min-width:140px; }
.bar { position:sticky; bottom:0; background:#12121f; border-top:1px solid #2a2a4a;
  padding:14px 20px; display:flex; justify-content:space-between; align-items:center; gap:12px; }
.hide { display:none !important; }
.toast { position:fixed; bottom:80px; left:50%; transform:translateX(-50%); background:#2ECC71;
  color:#062; padding:11px 22px; border-radius:10px; font-weight:600; opacity:0;
  transition:.3s; pointer-events:none; z-index:99; max-width:90vw; }
.toast.show { opacity:1; }
.toast.err { background:#E74C3C; color:#fff; }
.pfp { display:flex; align-items:center; gap:14px; margin-bottom:14px; }
.pfp img { width:76px; height:76px; border-radius:50%; border:2px solid #2a2a4a; }
.mini { background:#7B2FBE; border:0; border-radius:8px; color:#fff; padding:8px 14px;
  font-size:13px; font-weight:600; cursor:pointer; }
.mini.del { background:#3a2233; color:#ff8080; }
.mini.ghost { background:transparent; border:1px solid #3a3a5a; color:#b9b9cc; }
.item { display:flex; justify-content:space-between; align-items:center; gap:10px;
  padding:10px 0; border-bottom:1px solid #23233d; font-size:14px; }
.tag { display:inline-block; background:#7B2FBE22; border:1px solid #7B2FBE55; color:#c4b5fd;
  border-radius:6px; padding:1px 8px; font-size:11px; }
.note { color:#6b6b8a; font-size:12px; margin-top:8px; }
"""
    av = f'<img src="{avatar}" alt="">' if avatar else ""
    body = f"""<div class="wrap">
<header>
  <div><h1>🤖 Yoran Studios</h1><div style="color:#8b8ba7;font-size:13px">Bot control panel</div></div>
  <div class="who">{av}<span>{name}</span><a class="btn ghost" style="padding:7px 14px" href="/logout">Sign out</a></div>
</header>
<nav>
  <button class="on" data-tab="overview">📊 Overview</button>
  <button data-tab="bot">🤖 Bot</button>
  <button data-tab="server">🏠 Server</button>
  <button data-tab="economy">🪙 Economy</button>
  <button data-tab="levels">📈 Levels</button>
  <button data-tab="games">🎮 Games</button>
  <button data-tab="shop">🛒 Shop</button>
  <button data-tab="members">👥 Members</button>
  <button data-tab="announce">📢 Announce</button>
  <button data-tab="channels">⚙️ Channels</button>
  <button data-tab="boards">🏆 Boards</button>
</nav>

<section id="overview"><div class="grid" id="stats"></div></section>

<section id="bot" class="hide">
  <div class="cols">
    <div class="card">
      <h2>Identity</h2>
      <div class="pfp"><img id="botAvatar" src=""><div>
        <button class="mini" onclick="botFile.click()">Change avatar</button>
        <input type="file" id="botFile" accept="image/*" class="hide">
        <div class="note">PNG/JPG/GIF · max 8 MB</div>
      </div></div>
      <div class="field"><label>Bot username</label><input id="botName"></div>
      <button class="mini" id="saveBot">Save identity</button>
      <div class="note">⚠️ Discord only allows 2 username changes per hour.</div>
    </div>
    <div class="card">
      <h2>Presence</h2>
      <div class="field"><label>Status</label><select id="pStatus"></select></div>
      <div class="row">
        <div class="field"><label>Activity</label><select id="pType"></select></div>
        <div class="field"><label>Text</label><input id="pName" placeholder="/help • Yoran Studios"></div>
      </div>
      <button class="mini" id="savePresence">Save presence</button>
      <div class="note">Applies instantly and survives restarts.</div>
    </div>
  </div>
</section>

<section id="server" class="hide">
  <div class="card" style="max-width:520px">
    <h2>Server identity</h2>
    <div class="pfp"><img id="gIcon" src=""><div>
      <button class="mini" onclick="gFile.click()">Change icon</button>
      <input type="file" id="gFile" accept="image/*" class="hide">
      <div class="note">Shown as the server icon</div>
    </div></div>
    <div class="field"><label>Server name</label><input id="gName"></div>
    <button class="mini" id="saveGuild">Save server</button>
  </div>
</section>

<section id="economy" class="hide">
  <div class="card"><h2>Economy tuning</h2><div id="econ-fields"></div></div>
</section>

<section id="levels" class="hide">
  <div class="cols">
    <div class="card"><h2>Levels &amp; XP</h2><div id="lvl-fields"></div></div>
    <div>
      <div class="card" style="margin-bottom:16px"><h2>Trivia</h2><div id="triv-fields"></div></div>
      <div class="card"><h2>Counting</h2><div id="count-fields"></div></div>
    </div>
  </div>
</section>

<section id="games" class="hide">
  <div class="cols">
    <div class="card"><h2>Registered games</h2><div id="gameList"></div></div>
    <div class="card"><h2>Add a game</h2>
      <div class="field"><label>Name</label><input id="ngName"></div>
      <div class="field"><label>Status</label><select id="ngStatus"></select></div>
      <div class="field"><label>Description</label><textarea id="ngDesc"></textarea></div>
      <div class="field"><label>Image URL (optional)</label><input id="ngImg" placeholder="https://..."></div>
      <button class="mini" id="addGame">Add game</button>
      <div class="note">A 🔔 notify role is created automatically.</div>
    </div>
  </div>
</section>

<section id="shop" class="hide">
  <div class="cols">
    <div class="card"><h2>Shop items</h2><div id="shopList"></div></div>
    <div class="card"><h2>Add an item</h2>
      <div class="field"><label>Item name</label><input id="nsName"></div>
      <div class="field"><label>Price</label><input id="nsPrice" type="number" min="1" value="1000"></div>
      <div class="field"><label>Role granted</label><select id="nsRole"></select></div>
      <button class="mini" id="addShop">Add item</button>
    </div>
  </div>
</section>

<section id="members" class="hide">
  <div class="card">
    <h2>Members &amp; balances</h2>
    <div class="field"><input id="mSearch" placeholder="Search by name or ID..."></div>
    <table id="memberList"></table>
    <div class="note">Top 25 by net worth. Use +/− to give or take coins.</div>
  </div>
</section>

<section id="announce" class="hide">
  <div class="card" style="max-width:620px">
    <h2>Send an announcement</h2>
    <div class="row">
      <div class="field"><label>Channel</label><select id="aChannel"></select></div>
      <div class="field"><label>Ping role (optional)</label><select id="aRole"></select></div>
    </div>
    <div class="field"><label>Title</label><input id="aTitle"></div>
    <div class="field"><label>Message</label><textarea id="aDesc"></textarea></div>
    <div class="row">
      <div class="field"><label>Color</label><input id="aColor" type="color" value="#7B2FBE" style="height:38px;padding:3px"></div>
      <div class="field"><label>Image URL (optional)</label><input id="aImg" placeholder="https://..."></div>
    </div>
    <button class="mini" id="sendAnn">Send announcement</button>
  </div>
</section>

<section id="channels" class="hide">
  <div class="cols">
    <div class="card"><h2>Log channels</h2>
      <div class="field"><label>Ban logs</label><select id="c_ban_logs"></select></div>
      <div class="field"><label>Mod logs</label><select id="c_mod_logs"></select></div>
      <div class="field"><label>Action logs</label><select id="c_action_logs"></select></div>
      <div class="field"><label>AutoMod logs</label><select id="c_automod_logs"></select></div>
    </div>
    <div class="card"><h2>Features</h2>
      <div class="field"><label>Ticket logs</label><select id="c_ticket_logs"></select></div>
      <div class="field"><label>Ticket transcripts</label><select id="c_ticket_transcripts"></select></div>
      <div class="field"><label>Counting channel</label><select id="c_counting_channel"></select></div>
      <div class="field"><label>Member counter (voice)</label><select id="c_membercount_channel"></select></div>
      <button class="mini" id="saveChannels">Save channels</button>
      <div class="note" id="countInfo"></div>
    </div>
  </div>
</section>

<section id="boards" class="hide">
  <div class="cols">
    <div class="card"><h2>🪙 Coins</h2><table id="lb-coins"></table></div>
    <div class="card"><h2>📈 Levels</h2><table id="lb-levels"></table></div>
    <div class="card"><h2>💬 Messages</h2><table id="lb-messages"></table></div>
    <div class="card"><h2>📨 Invites</h2><table id="lb-invites"></table></div>
  </div>
</section>
</div>

<div class="bar hide" id="savebar">
  <span style="color:#8b8ba7;font-size:14px">You have unsaved tuning changes</span>
  <div style="display:flex;gap:8px">
    <button class="btn ghost" onclick="location.reload()">Discard</button>
    <button class="btn" id="saveBtn">Save changes</button>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const LABELS = {{
  daily_min:["Daily reward — min",""], daily_max:["Daily reward — max",""],
  daily_cooldown:["/daily cooldown","seconds"],
  work_min:["Work pay — min","no job"], work_max:["Work pay — max","no job"],
  work_cooldown:["/work cooldown","seconds"],
  beg_min:["Beg — min",""], beg_max:["Beg — max",""], beg_cooldown:["/beg cooldown","seconds"],
  beg_nothing_chance:["Beg fail chance","0-1"],
  crime_cooldown:["/crime cooldown","seconds"], crime_success_chance:["Crime success chance","0-1"],
  crime_win_min:["Crime win — min",""], crime_win_max:["Crime win — max",""],
  crime_fail_min:["Crime fine — min",""], crime_fail_max:["Crime fine — max",""],
  rob_cooldown:["/rob cooldown","seconds"], rob_success_chance:["Rob success chance","0-1"],
  rob_min_target_balance:["Min. target wallet","to be robbable"],
  rob_steal_pct_min:["Rob steal % — min","0-1"], rob_steal_pct_max:["Rob steal % — max","0-1"],
  rob_fine_pct_min:["Rob fine % — min","0-1"], rob_fine_pct_max:["Rob fine % — max","0-1"],
  rob_fine_min:["Rob fine floor",""], gamble_cooldown:["Gambling cooldown","seconds"],
  xp_min:["XP per message — min",""], xp_max:["XP per message — max",""],
  xp_cooldown:["XP cooldown","seconds — anti-spam"],
  cooldown:["/trivia cooldown","seconds"], reward_min:["Trivia reward — min",""], reward_max:["Trivia reward — max",""],
  milestone_every:["Milestone every","counts"], milestone_reward:["Milestone reward","coins"],
}};
const $=(s)=>document.querySelector(s);
const esc=(s)=>String(s??"").replace(/[<>&"]/g,c=>({{"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}}[c]));
let dirty=false, CHANNELS=[], ROLES=[], newAvatar=null, newIcon=null;

function toast(msg,err){{const t=$("#toast");t.textContent=msg;t.className="toast show"+(err?" err":"");setTimeout(()=>t.className="toast",2600);}}
async function readErr(r){{
  const txt=await r.text().catch(()=>"");
  try{{const j=JSON.parse(txt); if(j.error) return j.error;}}catch(e){{}}
  if(r.status===401) return "Session expired — reload and sign in again.";
  if(r.status===403) return "You don't have permission for that.";
  if(r.status===413) return "That file is too large.";
  return `Error ${{r.status}}${{txt?": "+txt.slice(0,120):""}}`;
}}
async function jget(u){{const r=await fetch(u);if(!r.ok)throw new Error(await readErr(r));return r.json();}}
async function jpost(u,b,m){{
  const r=await fetch(u,{{method:m||"POST",headers:{{"Content-Type":"application/json"}},body:b?JSON.stringify(b):null}});
  if(!r.ok) throw new Error(await readErr(r));
  return r.json().catch(()=>({{}}));
}}
function busy(btn,on,label){{btn.disabled=on;btn.textContent=on?"Saving...":label;}}
function fileToData(input,cb){{
  const f=input.files[0]; if(!f) return;
  if(f.type.indexOf("image/")!==0) return toast("Use a PNG, JPG or GIF image",1);
  if(f.size>7500000) return toast(`That image is ${{(f.size/1048576).toFixed(1)}} MB — keep it under 7 MB`,1);
  const rd=new FileReader();
  rd.onerror=()=>toast("Could not read that file",1);
  rd.onload=()=>cb(rd.result);
  rd.readAsDataURL(f);
}}
function opts(list,sel,none){{
  return (none?`<option value="">— none —</option>`:"")+
    list.map(o=>`<option value="${{o.id}}" ${{String(o.id)===String(sel)?"selected":""}}>${{esc(o.name)}}</option>`).join("");
}}

function field(section,key,val){{
  const [lab,hint]=LABELS[key]||[key,""];
  const step=Number.isInteger(val)?"1":"0.01";
  return `<div class="set"><label>${{lab}}${{hint?`<small>${{hint}}</small>`:""}}</label>
    <input type="number" step="${{step}}" value="${{val}}" data-s="${{section}}" data-k="${{key}}"></div>`;
}}
function renderSettings(cfg){{
  $("#econ-fields").innerHTML=Object.entries(cfg.economy).map(([k,v])=>field("economy",k,v)).join("");
  $("#lvl-fields").innerHTML=Object.entries(cfg.levels).map(([k,v])=>field("levels",k,v)).join("");
  $("#triv-fields").innerHTML=Object.entries(cfg.trivia).map(([k,v])=>field("trivia",k,v)).join("");
  $("#count-fields").innerHTML=Object.entries(cfg.counting).map(([k,v])=>field("counting",k,v)).join("");
  document.querySelectorAll(".set input").forEach(i=>i.addEventListener("input",()=>{{dirty=true;$("#savebar").classList.remove("hide");}}));
}}
function statCard(k,v){{return `<div class="stat"><div class="k">${{k}}</div><div class="v">${{v}}</div></div>`;}}
function renderStats(s){{
  $("#stats").innerHTML=[
    statCard("Members",(s.members||0).toLocaleString()),
    statCard("Humans",(s.humans||0).toLocaleString()),
    statCard("Latency",s.latency_ms+" ms"),
    statCard("Commands",s.commands),
    statCard("OG",(s.og||0).toLocaleString()),
    statCard("VIP",(s.vip||0)+" / 100"),
    statCard("Followers",(s.followers||0).toLocaleString()),
    statCard("Coins in circulation",(s.coins_circulating||0).toLocaleString()),
    statCard("Messages tracked",(s.tracked_messages||0).toLocaleString()),
    statCard("Ranked members",(s.ranked_users||0).toLocaleString()),
    statCard("Channels",s.channels),
    statCard("Roles",s.roles),
  ].join("");
}}
function renderBoard(id,rows){{
  $(id).innerHTML=rows.length?rows.map((r,i)=>
    `<tr><td class="pos">${{i+1}}</td><td>${{esc(r.name)}}</td><td>${{r.extra?esc(r.extra)+" · ":""}}${{(r.value||0).toLocaleString()}}</td></tr>`
  ).join(""):`<tr><td style="color:#6b6b8a">No data yet</td></tr>`;
}}
function renderBot(b){{
  $("#botAvatar").src=b.avatar+(b.avatar.includes("?")?"&":"?")+"t="+Date.now(); $("#botName").value=b.username;
  $("#pStatus").innerHTML=opts(b.status_options.map(o=>({{id:o,name:o}})),b.presence.status);
  $("#pType").innerHTML=opts(b.type_options.map(o=>({{id:o,name:o}})),b.presence.activity_type);
  $("#pName").value=b.presence.activity_name;
}}
function renderGames(d){{
  $("#ngStatus").innerHTML=opts(d.status_options.map(o=>({{id:o,name:o}})));
  $("#gameList").innerHTML=d.games.length?d.games.map(g=>
    `<div class="item"><div><b>${{esc(g.name)}}</b> <span class="tag">${{esc(g.status)}}</span>
      <div style="color:#8b8ba7;font-size:12px">${{esc(g.description).slice(0,80)}}</div></div>
      <button class="mini del" data-game="${{esc(g.id)}}">Remove</button></div>`).join("")
    :`<div style="color:#6b6b8a">No games registered yet.</div>`;
  document.querySelectorAll("[data-game]").forEach(b=>b.onclick=async()=>{{
    if(!confirm("Remove this game and its notify role?"))return;
    try{{renderGames(await jpost("/api/games/"+b.dataset.game,null,"DELETE"));toast("Game removed");}}
    catch(e){{toast(e.message,1);}}
  }});
}}
function renderShop(items){{
  $("#shopList").innerHTML=items.length?items.map(i=>
    `<div class="item"><div><b>${{esc(i.name)}}</b> <span class="tag">${{i.price.toLocaleString()}} coins</span>
      <div style="color:#8b8ba7;font-size:12px">grants ${{esc(i.role_name)}}</div></div>
      <button class="mini del" data-shop="${{encodeURIComponent(i.name)}}">Remove</button></div>`).join("")
    :`<div style="color:#6b6b8a">The shop is empty.</div>`;
  document.querySelectorAll("[data-shop]").forEach(b=>b.onclick=async()=>{{
    try{{renderShop(await jpost("/api/shop/"+b.dataset.shop,null,"DELETE"));toast("Item removed");}}
    catch(e){{toast(e.message,1);}}
  }});
}}
function renderMembers(list){{
  $("#memberList").innerHTML=list.length?list.map(m=>
    `<tr><td>${{esc(m.name)}}<div style="color:#6b6b8a;font-size:11px">${{m.id}}</div></td>
     <td>👛 ${{m.wallet.toLocaleString()}} · 🏦 ${{m.bank.toLocaleString()}}</td>
     <td><button class="mini" data-give="${{m.id}}">+</button>
         <button class="mini del" data-take="${{m.id}}">−</button></td></tr>`).join("")
    :`<tr><td style="color:#6b6b8a">No members found</td></tr>`;
  document.querySelectorAll("[data-give]").forEach(b=>b.onclick=()=>coins(b.dataset.give,1));
  document.querySelectorAll("[data-take]").forEach(b=>b.onclick=()=>coins(b.dataset.take,-1));
}}
async function coins(uid,sign){{
  const raw=prompt(sign>0?"How many coins to give?":"How many coins to remove?");
  const n=parseInt(raw,10); if(!n||n<=0)return;
  try{{await jpost("/api/economy/give",{{user_id:uid,amount:n*sign}});
    toast(sign>0?`Gave ${{n}} coins`:`Removed ${{n}} coins`); loadMembers();}}
  catch(e){{toast(e.message,1);}}
}}
async function loadMembers(){{renderMembers(await jget("/api/members?q="+encodeURIComponent($("#mSearch").value)));}}
function renderConfig(c){{
  ["ban_logs","mod_logs","action_logs","automod_logs","ticket_logs","ticket_transcripts","counting_channel","membercount_channel"]
    .forEach(k=>{{const el=$("#c_"+k); if(el) el.innerHTML=opts(CHANNELS,c[k],true);}});
  $("#countInfo").textContent=`Counting: at ${{c.counting_current||0}} · high score ${{c.counting_high||0}}`;
}}

document.querySelectorAll("nav button").forEach(b=>b.addEventListener("click",()=>{{
  document.querySelectorAll("nav button").forEach(x=>x.classList.remove("on"));
  b.classList.add("on");
  document.querySelectorAll("section").forEach(s=>s.classList.toggle("hide",s.id!==b.dataset.tab));
  $("#savebar").classList.toggle("hide",!(dirty&&["economy","levels"].includes(b.dataset.tab)));
}}));

$("#saveBtn").onclick=async()=>{{
  const out={{}};
  document.querySelectorAll(".set input").forEach(i=>{{
    out[i.dataset.s]=out[i.dataset.s]||{{}};
    out[i.dataset.s][i.dataset.k]=parseFloat(i.value);
  }});
  try{{renderSettings(await jpost("/api/settings",out));dirty=false;$("#savebar").classList.add("hide");toast("Saved — live on the bot");}}
  catch(e){{toast(e.message,1);}}
}};
$("#botFile").onchange=()=>fileToData($("#botFile"),d=>{{newAvatar=d;$("#botAvatar").src=d;toast("Avatar ready — press Save identity");}});
$("#gFile").onchange=()=>fileToData($("#gFile"),d=>{{newIcon=d;$("#gIcon").src=d;toast("Icon ready — press Save server");}});
$("#saveBot").onclick=async(e)=>{{
  const b=e.target; busy(b,true);
  try{{renderBot(await jpost("/api/bot",{{username:$("#botName").value,avatar:newAvatar||""}}));
    newAvatar=null;toast("Bot identity updated");}}
  catch(err){{toast(err.message,1);}}
  finally{{busy(b,false,"Save identity");}}
}};
$("#savePresence").onclick=async()=>{{
  try{{renderBot(await jpost("/api/bot",{{presence:{{status:$("#pStatus").value,activity_type:$("#pType").value,activity_name:$("#pName").value}}}}));
    toast("Presence updated");}}
  catch(e){{toast(e.message,1);}}
}};
$("#saveGuild").onclick=async(e)=>{{
  const b=e.target; busy(b,true);
  try{{const g=await jpost("/api/guild",{{name:$("#gName").value,icon:newIcon||""}});
    $("#gIcon").src=g.icon?g.icon+"?t="+Date.now():"";$("#gName").value=g.name;newIcon=null;toast("Server updated");}}
  catch(err){{toast(err.message,1);}}
  finally{{busy(b,false,"Save server");}}
}};
$("#addGame").onclick=async()=>{{
  try{{renderGames(await jpost("/api/games",{{name:$("#ngName").value,status:$("#ngStatus").value,
    description:$("#ngDesc").value,image_url:$("#ngImg").value}}));
    $("#ngName").value=$("#ngDesc").value=$("#ngImg").value="";toast("Game added");}}
  catch(e){{toast(e.message,1);}}
}};
$("#addShop").onclick=async()=>{{
  try{{renderShop(await jpost("/api/shop",{{name:$("#nsName").value,price:$("#nsPrice").value,role_id:$("#nsRole").value}}));
    $("#nsName").value="";toast("Item added");}}
  catch(e){{toast(e.message,1);}}
}};
$("#sendAnn").onclick=async()=>{{
  try{{const r=await jpost("/api/announce",{{channel_id:$("#aChannel").value,ping_role_id:$("#aRole").value,
    title:$("#aTitle").value,description:$("#aDesc").value,color:$("#aColor").value,image_url:$("#aImg").value}});
    $("#aTitle").value=$("#aDesc").value=$("#aImg").value="";toast("Sent to #"+r.channel);}}
  catch(e){{toast(e.message,1);}}
}};
$("#saveChannels").onclick=async()=>{{
  const out={{}};
  ["ban_logs","mod_logs","action_logs","automod_logs","ticket_logs","ticket_transcripts","counting_channel","membercount_channel"]
    .forEach(k=>out[k]=$("#c_"+k).value);
  try{{renderConfig(await jpost("/api/config",out));toast("Channels saved");}}
  catch(e){{toast(e.message,1);}}
}};
let searchTimer;
$("#mSearch").oninput=()=>{{clearTimeout(searchTimer);searchTimer=setTimeout(loadMembers,300);}};
window.addEventListener("beforeunload",e=>{{if(dirty){{e.preventDefault();e.returnValue="";}}}});

(async()=>{{
  try{{
    renderStats(await jget("/api/stats"));
    renderSettings(await jget("/api/settings"));
    renderBot(await jget("/api/bot"));
    const g=await jget("/api/guild"); $("#gIcon").src=g.icon; $("#gName").value=g.name;
    CHANNELS=await jget("/api/channels"); ROLES=await jget("/api/roles");
    $("#aChannel").innerHTML=opts(CHANNELS); $("#aRole").innerHTML=opts(ROLES,"",true);
    $("#nsRole").innerHTML=opts(ROLES);
    renderGames(await jget("/api/games"));
    renderShop(await jget("/api/shop"));
    renderConfig(await jget("/api/config"));
    loadMembers();
    const lb=await jget("/api/leaderboards");
    renderBoard("#lb-coins",lb.coins); renderBoard("#lb-levels",lb.levels);
    renderBoard("#lb-messages",lb.messages); renderBoard("#lb-invites",lb.invites);
    setInterval(async()=>{{try{{renderStats(await jget("/api/stats"));}}catch(e){{}}}},30000);
  }}catch(e){{toast("Failed to load: "+e.message,1);}}
}})();
</script>"""
    return _shell(body, css)


async def start_dashboard(bot: discord.Client, port: int):
    app = web.Application(middlewares=[error_middleware, auth_middleware], client_max_size=MAX_UPLOAD)
    app["bot"] = bot
    app.add_routes([
        web.get("/", handle_index),
        web.get("/login", handle_login),
        web.get("/callback", handle_callback),
        web.get("/logout", handle_logout),
        web.get("/health", handle_health),
        web.get("/api/stats", api_stats),
        web.get("/api/leaderboards", api_leaderboards),
        web.get("/api/settings", api_settings_get),
        web.post("/api/settings", api_settings_post),
        web.get("/api/bot", api_bot_get),
        web.post("/api/bot", api_bot_post),
        web.get("/api/guild", api_guild_get),
        web.post("/api/guild", api_guild_post),
        web.get("/api/channels", api_channels),
        web.get("/api/roles", api_roles),
        web.get("/api/games", api_games_get),
        web.post("/api/games", api_games_post),
        web.delete("/api/games/{gid}", api_games_delete),
        web.get("/api/shop", api_shop_get),
        web.post("/api/shop", api_shop_post),
        web.delete("/api/shop/{name}", api_shop_delete),
        web.get("/api/members", api_members),
        web.post("/api/economy/give", api_economy_give),
        web.post("/api/announce", api_announce),
        web.get("/api/config", api_config_get),
        web.post("/api/config", api_config_post),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    if not (CLIENT_ID and CLIENT_SECRET):
        print("[Dashboard] CLIENT_ID/CLIENT_SECRET missing — login will fail", flush=True)
    if not os.getenv("SESSION_SECRET"):
        print("[Dashboard] SESSION_SECRET not set — sessions reset on every restart", flush=True)
    print(f"[Dashboard] Listening on 0.0.0.0:{port}", flush=True)
