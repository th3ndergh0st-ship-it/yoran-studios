import json
import os
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import SUCCESS, ERROR
from utils import is_admin

COUNT_FILE = "data/membercount.json"
NAME_FORMAT = "Members: {count}"
# Discord only allows ~2 channel renames per 10 minutes, so between the
# instant updates we leave a safety gap and let the loop catch up.
MIN_SECONDS_BETWEEN_RENAMES = 330


def _load() -> dict:
    if not os.path.exists(COUNT_FILE):
        return {}
    with open(COUNT_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(COUNT_FILE, "w") as f:
        json.dump(data, f, indent=2)


class MemberCount(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_rename: dict[int, float] = {}

    async def cog_load(self):
        self.refresh_counters.start()

    async def cog_unload(self):
        self.refresh_counters.cancel()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have the required role for this command.", color=ERROR),
                ephemeral=True,
            )

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

    # ── Setup command ────────────────────────────────────────────────────────────

    @app_commands.command(
        name="setup-membercount",
        description="Set up a locked voice channel that shows the live member count",
    )
    @app_commands.describe(channel="Existing voice channel to use — leave empty to create a new one")
    @is_admin()
    async def setup_membercount(self, interaction: discord.Interaction, channel: discord.VoiceChannel = None):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        if channel is None:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=False),
                guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True),
            }
            channel = await guild.create_voice_channel(
                name=NAME_FORMAT.format(count=guild.member_count),
                overwrites=overwrites,
                position=0,
                reason=f"Member count channel created by {interaction.user}",
            )
        else:
            try:
                await channel.set_permissions(guild.default_role, connect=False)
                await channel.edit(name=NAME_FORMAT.format(count=guild.member_count), reason="Member count setup")
            except discord.HTTPException:
                pass

        data = _load()
        data[str(guild.id)] = channel.id
        _save(data)
        self._last_rename[guild.id] = time.time()

        await interaction.followup.send(
            embed=discord.Embed(
                description=(
                    f"✅ Member counter active on **{channel.name}**.\n"
                    "It updates when members join/leave (Discord limits renames to ~2 per 10 min, "
                    "so during heavy traffic it syncs every 10 minutes)."
                ),
                color=SUCCESS,
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MemberCount(bot))
