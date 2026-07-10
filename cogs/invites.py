import json
import os

import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY
import storage

INVITES_FILE = storage.path("invites.json")
STUDIOS_GUILD_ID = 1523445628204482620


def _load() -> dict:
    if not os.path.exists(INVITES_FILE):
        return {}
    with open(INVITES_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(INVITES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_invite_counts(guild_id: int) -> dict:
    """{inviter_id: invite_count} — used by /leaderboard invites."""
    return _load().get(str(guild_id), {}).get("by_user", {})


class Invites(commands.Cog):
    """Tracks which invite each new member used, crediting the inviter.

    Works by snapshotting invite use-counts and diffing them when someone
    joins — the invite whose counter went up is the one they used.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {guild_id: {code: (uses, inviter_id)}}
        self._cache: dict[int, dict[str, tuple[int, int | None]]] = {}

    async def _refresh_cache(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except discord.HTTPException:
            return
        self._cache[guild.id] = {
            inv.code: (inv.uses or 0, inv.inviter.id if inv.inviter else None)
            for inv in invites
        }

    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.get_guild(STUDIOS_GUILD_ID)
        if guild and guild.id not in self._cache:
            await self._refresh_cache(guild)
            print(f"[Invites] Cached {len(self._cache.get(guild.id, {}))} invites for {guild.name}", flush=True)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild and invite.guild.id in self._cache:
            self._cache[invite.guild.id][invite.code] = (invite.uses or 0, invite.inviter.id if invite.inviter else None)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild and invite.guild.id in self._cache:
            self._cache[invite.guild.id].pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if guild.id != STUDIOS_GUILD_ID or member.bot:
            return
        old = self._cache.get(guild.id, {})
        try:
            invites = await guild.invites()
        except discord.HTTPException:
            return

        used_inviter = None
        new_cache = {}
        for inv in invites:
            uses = inv.uses or 0
            inviter_id = inv.inviter.id if inv.inviter else None
            new_cache[inv.code] = (uses, inviter_id)
            if uses > old.get(inv.code, (0, None))[0]:
                used_inviter = inviter_id
        self._cache[guild.id] = new_cache

        if not used_inviter:
            return
        data = _load()
        g = data.setdefault(str(guild.id), {})
        by_user = g.setdefault("by_user", {})
        by_user[str(used_inviter)] = by_user.get(str(used_inviter), 0) + 1
        g.setdefault("inviter_of", {})[str(member.id)] = str(used_inviter)
        _save(data)

    # ── Command ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="invites", description="See how many members someone has invited")
    @app_commands.describe(member="Member to check (defaults to you)")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        g = _load().get(str(interaction.guild.id), {})
        count = g.get("by_user", {}).get(str(target.id), 0)
        inviter_id = g.get("inviter_of", {}).get(str(target.id))

        embed = discord.Embed(title=f"📨  {target.display_name}'s Invites", color=PRIMARY)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="✉️ Members invited", value=f"`{count}`", inline=True)
        if inviter_id:
            embed.add_field(name="🙋 Invited by", value=f"<@{inviter_id}>", inline=True)
        embed.set_footer(text="Tracked since the invite tracker went live")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
