import json
import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, GOLD
import storage

LEVELS_FILE = storage.path("levels.json")

XP_PER_MESSAGE = (15, 25)
XP_COOLDOWN = 60  # seconds between XP gains per member (anti-spam)

# Milestone roles that already exist in the server. When a member reaches
# one of these levels they get the role (and lose the previous milestone).
LEVEL_ROLES = {
    5: "Level 5", 10: "Level 10", 20: "Level 20", 30: "Level 30",
    40: "Level 40", 50: "Level 50", 60: "Level 60", 70: "Level 70",
    80: "Level 80",
}

# Channels that never grant XP (counting spam, bot commands).
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


class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── XP gain ──────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id in NO_XP_CHANNEL_IDS:
            return

        data = _load()
        guild_data = data.setdefault(str(message.guild.id), {})
        user = guild_data.setdefault(str(message.author.id), {"xp": 0, "level": 0, "last_xp": 0, "messages": 0})

        # every message counts toward the message leaderboard...
        user["messages"] = user.get("messages", 0) + 1

        now = time.time()
        if now - user.get("last_xp", 0) < XP_COOLDOWN:
            _save(data)
            return

        # ...but XP stays cooldown-gated so spam doesn't level you up
        user["xp"] += random.randint(*XP_PER_MESSAGE)
        user["last_xp"] = now

        leveled_up = False
        while user["xp"] >= xp_needed(user["level"]):
            user["xp"] -= xp_needed(user["level"])
            user["level"] += 1
            leveled_up = True

        level = user["level"]
        # Guard against duplicate announcements (e.g. two bot processes
        # overlapping during a redeploy): only announce levels we haven't
        # announced before, and persist that marker with the XP data.
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
        """Give the milestone role for `level` and remove lower milestone roles."""
        target_name = LEVEL_ROLES.get(level)
        if not target_name:
            return
        target = discord.utils.get(member.guild.roles, name=target_name)
        if target and target not in member.roles:
            await member.add_roles(target, reason=f"Reached level {level}")
        lower_names = {name for lvl, name in LEVEL_ROLES.items() if lvl < level}
        to_remove = [r for r in member.roles if r.name in lower_names]
        if to_remove:
            await member.remove_roles(*to_remove, reason=f"Superseded by {target_name}")

    # ── Commands ─────────────────────────────────────────────────────────────────

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

        # position in server ranking
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
