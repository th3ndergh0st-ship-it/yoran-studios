import json
import os
import random
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, GOLD
import storage
import settings

LEVELS_FILE = storage.path("levels.json")

LEVEL_ROLES = {
    5: "Level 5", 10: "Level 10", 20: "Level 20", 30: "Level 30",
    40: "Level 40", 50: "Level 50", 60: "Level 60", 70: "Level 70",
    80: "Level 80",
}

NO_XP_CHANNEL_IDS = {1524143534998032656}


def xp_needed(level: int) -> int:
    """XP required to advance FROM `level` to the next one (MEE6-style curve)."""
    return 5 * level * level + 50 * level + 100


def _load() -> dict:
    if not os.path.exists(LEVELS_FILE):
        return {}
    with open(LEVELS_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(LEVELS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_guild_stats(guild_id: int) -> dict:
    """Public accessor for other cogs (e.g. the unified /leaderboard):
    returns {user_id: {"xp", "level", "messages", ...}} for a guild."""
    return _load().get(str(guild_id), {})


def current_day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_week_key() -> str:
    iso = datetime.now(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


STUDIOS_GUILD_ID = 1523445628204482620
BACKFILL_KEY = "backfilled_guilds"


class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._backfill_started = False


    @commands.Cog.listener()
    async def on_ready(self):
        if self._backfill_started:
            return
        self._backfill_started = True
        guild = self.bot.get_guild(STUDIOS_GUILD_ID)
        if guild is None:
            return
        if str(guild.id) in _load().get(BACKFILL_KEY, []):
            return
        self.bot.loop.create_task(self._backfill_guild(guild))

    async def _backfill_guild(self, guild: discord.Guild):
        print(f"[Levels] Backfilling message counts for {guild.name}...", flush=True)
        counts: dict[str, int] = {}
        channels_done = 0
        for channel in guild.text_channels:
            if channel.id in NO_XP_CHANNEL_IDS:
                continue
            try:
                async for msg in channel.history(limit=None):
                    if msg.author.bot:
                        continue
                    uid = str(msg.author.id)
                    counts[uid] = counts.get(uid, 0) + 1
                channels_done += 1
            except (discord.Forbidden, discord.HTTPException):
                continue

        data = _load()
        guild_data = data.setdefault(str(guild.id), {})
        for uid, scanned in counts.items():
            user = guild_data.setdefault(uid, {"xp": 0, "level": 0, "last_xp": 0, "messages": 0})
            user["messages"] = max(user.get("messages", 0), scanned)
        data.setdefault(BACKFILL_KEY, []).append(str(guild.id))
        _save(data)
        print(
            f"[Levels] Backfill done for {guild.name}: {sum(counts.values()):,} messages "
            f"across {channels_done} channels from {len(counts)} members",
            flush=True,
        )


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id in NO_XP_CHANNEL_IDS:
            return

        data = _load()
        guild_data = data.setdefault(str(message.guild.id), {})
        user = guild_data.setdefault(str(message.author.id), {"xp": 0, "level": 0, "last_xp": 0, "messages": 0})

        user["messages"] = user.get("messages", 0) + 1
        day, week = current_day_key(), current_week_key()
        if user.get("day_key") != day:
            user["day_key"], user["messages_day"] = day, 0
        if user.get("week_key") != week:
            user["week_key"], user["messages_week"] = week, 0
        user["messages_day"] = user.get("messages_day", 0) + 1
        user["messages_week"] = user.get("messages_week", 0) + 1

        now = time.time()
        if now - user.get("last_xp", 0) < settings.get("levels", "xp_cooldown"):
            _save(data)
            return

        user["xp"] += random.randint(settings.get("levels", "xp_min"), settings.get("levels", "xp_max"))
        user["last_xp"] = now

        leveled_up = False
        while user["xp"] >= xp_needed(user["level"]):
            user["xp"] -= xp_needed(user["level"])
            user["level"] += 1
            leveled_up = True

        level = user["level"]
        already_announced = user.get("announced", 0)
        should_announce = leveled_up and level > already_announced
        if should_announce:
            user["announced"] = level

        _save(data)

        if not should_announce:
            return

        try:
            if level in LEVEL_ROLES:
                await self._sync_level_role(message.author, level)
                await message.channel.send(
                    embed=discord.Embed(
                        description=(
                            f"🏆 GG {message.author.mention} — you reached **Level {level}** "
                            f"and earned the **{LEVEL_ROLES[level]}** role!"
                        ),
                        color=GOLD,
                    ),
                    delete_after=12,
                )
            else:
                await message.channel.send(
                    embed=discord.Embed(
                        description=f"🎉 {message.author.mention} leveled up to **Level {level}**!",
                        color=PRIMARY,
                    ),
                    delete_after=12,
                )
        except discord.HTTPException:
            pass

    async def _sync_level_role(self, member: discord.Member, level: int):
        """Give the milestone role for `level`. Milestone roles STACK — members
        keep every level role they've earned (Level 5 stays when you hit 10)."""
        target_name = LEVEL_ROLES.get(level)
        if not target_name:
            return
        target = discord.utils.get(member.guild.roles, name=target_name)
        if target and target not in member.roles:
            await member.add_roles(target, reason=f"Reached level {level}")


    @app_commands.command(name="rank", description="View your (or someone else's) level and XP")
    @app_commands.describe(member="Member to check")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        data = _load().get(str(interaction.guild.id), {})
        user = data.get(str(target.id), {"xp": 0, "level": 0})
        level, xp = user["level"], user["xp"]
        needed = xp_needed(level)

        filled = int((xp / needed) * 12) if needed else 0
        bar = "█" * filled + "░" * (12 - filled)

        ranked = sorted(data.items(), key=lambda kv: (kv[1].get("level", 0), kv[1].get("xp", 0)), reverse=True)
        position = next((i + 1 for i, (uid, _) in enumerate(ranked) if uid == str(target.id)), len(ranked) + 1)

        embed = discord.Embed(title=f"📊  {target.display_name}'s Rank", color=PRIMARY)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🏅 Level", value=f"`{level}`", inline=True)
        embed.add_field(name="⭐ Rank", value=f"`#{position}`", inline=True)
        embed.add_field(name="✨ XP", value=f"`{xp:,} / {needed:,}`", inline=True)
        embed.add_field(name="💬 Messages", value=f"`{user.get('messages', 0):,}`", inline=True)
        embed.add_field(name="Progress", value=f"`{bar}`", inline=False)
        next_milestone = next((lvl for lvl in sorted(LEVEL_ROLES) if lvl > level), None)
        if next_milestone:
            embed.set_footer(text=f"Next role reward at Level {next_milestone}: {LEVEL_ROLES[next_milestone]}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="levels", description="View the server's XP leaderboard")
    async def levels(self, interaction: discord.Interaction):
        data = _load().get(str(interaction.guild.id), {})
        ranked = sorted(data.items(), key=lambda kv: (kv[1].get("level", 0), kv[1].get("xp", 0)), reverse=True)[:10]
        embed = discord.Embed(title="🏆  Level Leaderboard", color=GOLD)
        if not ranked:
            embed.description = "Nobody has earned XP yet — start chatting!"
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, (uid, u) in enumerate(ranked):
                m = interaction.guild.get_member(int(uid))
                name = m.mention if m else f"<@{uid}>"
                prefix = medals[i] if i < 3 else f"`#{i + 1}`"
                lines.append(f"{prefix}  {name} — Level **{u.get('level', 0)}** (`{u.get('xp', 0):,}` xp)")
            embed.description = "\n".join(lines)
        embed.set_footer(text="Yoran Studios  •  Levels")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
