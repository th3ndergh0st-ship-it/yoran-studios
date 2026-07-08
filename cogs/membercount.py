import json
import os
import time

import discord
from discord.ext import commands, tasks

import storage
COUNT_FILE = storage.path("membercount.json")
NAME_FORMAT = "Members: {count}"
# Discord only allows ~2 channel renames per 10 minutes, so between the
# instant updates we leave a safety gap and let the loop catch up.
MIN_SECONDS_BETWEEN_RENAMES = 330


def _load() -> dict:
    if not os.path.exists(COUNT_FILE):
        return {}
    with open(COUNT_FILE, "r") as f:
        return json.load(f)


class MemberCount(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_rename: dict[int, float] = {}

    async def cog_load(self):
        self.refresh_counters.start()

    async def cog_unload(self):
        self.refresh_counters.cancel()

    # ── Updating ─────────────────────────────────────────────────────────────────

    async def _update_guild(self, guild: discord.Guild, force: bool = False):
        data = _load()
        ch_id = data.get(str(guild.id))
        if not ch_id:
            return
        channel = guild.get_channel(ch_id)
        if channel is None:
            return
        new_name = NAME_FORMAT.format(count=guild.member_count)
        if channel.name == new_name:
            return
        now = time.time()
        if not force and now - self._last_rename.get(guild.id, 0) < MIN_SECONDS_BETWEEN_RENAMES:
            return  # too soon — the 10-minute loop will catch it
        try:
            await channel.edit(name=new_name, reason="Member count update")
            self._last_rename[guild.id] = now
        except discord.HTTPException:
            pass

    @tasks.loop(minutes=10)
    async def refresh_counters(self):
        data = _load()
        for gid in list(data.keys()):
            guild = self.bot.get_guild(int(gid))
            if guild:
                await self._update_guild(guild, force=True)

    @refresh_counters.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._update_guild(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._update_guild(member.guild)

async def setup(bot: commands.Bot):
    await bot.add_cog(MemberCount(bot))
