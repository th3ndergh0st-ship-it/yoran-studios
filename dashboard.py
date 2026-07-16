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
import economy_data as econ

CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
BASE_URL = os.getenv("DASHBOARD_URL", "").rstrip("/")

STUDIOS_GUILD_ID = 1523445628204482620
DEV_ROLE_ID = 1523445699377627186
ALWAYS_ALLOWED_USER_IDS = {1230234714229444623}

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
    print(f"[Dashboard] Settings updated by {request['user_name']} ({request['user_id']})", flush=True)
    return web.json_response(updated)


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
.cols { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
td { padding:7px 4px; border-bottom:1px solid #23233d; }
td:last-child { text-align:right; color:#c4b5fd; font-variant-numeric:tabular-nums; }
.pos { color:#6b6b8a; width:28px; }
.set { display:grid; grid-template-columns:1fr 110px; gap:10px; align-items:center;
  padding:7px 0; border-bottom:1px solid #23233d; }
.set label { font-size:14px; color:#c9c9dd; }
.set small { display:block; color:#6b6b8a; font-size:11px; }
.set input { background:#0f0f1a; border:1px solid #3a3a5a; border-radius:8px; color:#e6e6f0;
  padding:7px 9px; font-size:14px; width:100%; text-align:right; }
.set input:focus { outline:0; border-color:#7B2FBE; }
.bar { position:sticky; bottom:0; background:#12121f; border-top:1px solid #2a2a4a;
  padding:14px 20px; display:flex; justify-content:space-between; align-items:center; gap:12px; }
.hide { display:none; }
.toast { position:fixed; bottom:80px; left:50%; transform:translateX(-50%); background:#2ECC71;
  color:#062; padding:10px 20px; border-radius:10px; font-weight:600; opacity:0; transition:.3s; }
.toast.show { opacity:1; }
.toast.err { background:#E74C3C; color:#fff; }
"""
    av = f'<img src="{avatar}" alt="">' if avatar else ""
    body = f"""<div class="wrap">
<header>
  <div><h1>🤖 Yoran Studios</h1><div style="color:#8b8ba7;font-size:13px">Bot control panel</div></div>
  <div class="who">{av}<span>{name}</span><a class="btn ghost" style="padding:7px 14px" href="/logout">Sign out</a></div>
</header>
<nav>
  <button class="on" data-tab="overview">📊 Overview</button>
  <button data-tab="economy">🪙 Economy</button>
  <button data-tab="levels">📈 Levels &amp; Trivia</button>
  <button data-tab="boards">🏆 Leaderboards</button>
</nav>

<section id="overview">
  <div class="grid" id="stats"></div>
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
  <span style="color:#8b8ba7;font-size:14px">You have unsaved changes</span>
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
let dirty=false, CFG={{}};
const $=(s)=>document.querySelector(s);
function toast(msg,err){{const t=$("#toast");t.textContent=msg;t.className="toast show"+(err?" err":"");setTimeout(()=>t.className="toast",2200);}}
function field(section,key,val){{
  const [lab,hint]=LABELS[key]||[key,""];
  const step=Number.isInteger(val)?"1":"0.01";
  return `<div class="set"><label>${{lab}}${{hint?`<small>${{hint}}</small>`:""}}</label>
    <input type="number" step="${{step}}" value="${{val}}" data-s="${{section}}" data-k="${{key}}"></div>`;
}}
function renderSettings(cfg){{
  CFG=cfg;
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
    `<tr><td class="pos">${{i+1}}</td><td>${{r.name}}</td><td>${{r.extra?r.extra+" · ":""}}${{(r.value||0).toLocaleString()}}</td></tr>`
  ).join(""):`<tr><td style="color:#6b6b8a">No data yet</td></tr>`;
}}
document.querySelectorAll("nav button").forEach(b=>b.addEventListener("click",()=>{{
  document.querySelectorAll("nav button").forEach(x=>x.classList.remove("on"));
  b.classList.add("on");
  ["overview","economy","levels","boards"].forEach(t=>$("#"+t).classList.toggle("hide",t!==b.dataset.tab));
}}));
$("#saveBtn").addEventListener("click",async()=>{{
  const out={{}};
  document.querySelectorAll(".set input").forEach(i=>{{
    out[i.dataset.s]=out[i.dataset.s]||{{}};
    out[i.dataset.s][i.dataset.k]=parseFloat(i.value);
  }});
  const r=await fetch("/api/settings",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(out)}});
  if(r.ok){{renderSettings(await r.json());dirty=false;$("#savebar").classList.add("hide");toast("Saved — live on the bot");}}
  else toast("Could not save",1);
}});
window.addEventListener("beforeunload",e=>{{if(dirty){{e.preventDefault();e.returnValue="";}}}});
(async()=>{{
  renderStats(await (await fetch("/api/stats")).json());
  renderSettings(await (await fetch("/api/settings")).json());
  const lb=await (await fetch("/api/leaderboards")).json();
  renderBoard("#lb-coins",lb.coins); renderBoard("#lb-levels",lb.levels);
  renderBoard("#lb-messages",lb.messages); renderBoard("#lb-invites",lb.invites);
  setInterval(async()=>renderStats(await (await fetch("/api/stats")).json()),30000);
}})();
</script>"""
    return _shell(body, css)


async def start_dashboard(bot: discord.Client, port: int):
    app = web.Application(middlewares=[auth_middleware])
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
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    if not (CLIENT_ID and CLIENT_SECRET):
        print("[Dashboard] CLIENT_ID/CLIENT_SECRET missing — login will fail", flush=True)
    if not os.getenv("SESSION_SECRET"):
        print("[Dashboard] SESSION_SECRET not set — sessions reset on every restart", flush=True)
    print(f"[Dashboard] Listening on 0.0.0.0:{port}", flush=True)
