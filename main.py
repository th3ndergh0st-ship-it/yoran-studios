import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands
import os
from dotenv import load_dotenv
from keepalive import start_keepalive
import storage

load_dotenv()
storage.bootstrap()

# This bot is exclusive to the Yoran Studios server. Slash commands are
# refused everywhere else — the Yoran Shop server has its own separate bot.
STUDIOS_GUILD_ID = 1523445628204482620

# Universal per-user cooldown between ANY two slash commands, so nobody can
# flood the bot with rapid-fire commands.
GLOBAL_COMMAND_COOLDOWN = 2.0


class StudiosOnlyTree(app_commands.CommandTree):
    _last_use: dict[int, float] = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is not None and interaction.guild.id != STUDIOS_GUILD_ID:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ This bot is exclusive to the **Yoran Studios** server.",
                    color=0xE74C3C,
                ),
                ephemeral=True,
            )
            return False

        now = time.monotonic()
        if now - self._last_use.get(interaction.user.id, 0.0) < GLOBAL_COMMAND_COOLDOWN:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="⏳ Slow down! Wait a couple of seconds between commands.",
                    color=0xF39C12,
                ),
                ephemeral=True,
            )
            return False
        self._last_use[interaction.user.id] = now
        return True


class Yoran(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            tree_cls=StudiosOnlyTree,
        )

    async def setup_hook(self):
        extensions = [
            "cogs.moderation",
            "cogs.announcements",
            "cogs.verification",
            "cogs.welcome",
            "cogs.tickets",
            "cogs.utility",
            "cogs.giveaway",
            "cogs.games",
            "cogs.economy",
            "cogs.education",
            "cogs.membercount",
            "cogs.logs",
            "cogs.counting",
            "cogs.levels",
            "cogs.invites",
            "cogs.verifysub",
        ]
        for ext in extensions:
            await self.load_extension(ext)

        # Register commands per-guild instead of globally so they only
        # show up inside Yoran Studios — not in any other server the bot
        # happens to be in.
        studios = discord.Object(STUDIOS_GUILD_ID)
        self.tree.copy_global_to(guild=studios)
        self.tree.clear_commands(guild=None)
        synced = await self.tree.sync(guild=studios)
        await self.tree.sync()  # push the now-empty global list so old global commands disappear
        print(f"[Yoran] Synced {len(synced)} slash commands to Yoran Studios", flush=True)

        port = int(os.getenv("PORT", "3000"))
        start_keepalive(port=port)

    async def on_ready(self):
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="/help • Yoran Studios",
            ),
            status=discord.Status.online,
        )
        print(f"[Yoran] Online · {self.user} · {len(self.guilds)} server(s)")

    async def _assign_unverified(self, member: discord.Member):
        role = discord.utils.get(member.guild.roles, name="Unverified")
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Auto-assigned on join")
            except discord.HTTPException as e:
                print(f"[Yoran] Could not assign Unverified to {member}: {e}", flush=True)

    async def on_member_join(self, member: discord.Member):
        if member.guild.id != STUDIOS_GUILD_ID:
            return
        # Community servers with rules screening keep new members "pending";
        # Discord forbids giving roles to pending members, so wait for
        # on_member_update to fire once they accept the rules.
        if member.pending:
            return
        await self._assign_unverified(member)

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id != STUDIOS_GUILD_ID:
            return
        if before.pending and not after.pending:
            await self._assign_unverified(after)

    async def on_guild_join(self, guild: discord.Guild):
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="👋 Yoran has arrived",
                    description=(
                        "Thanks for adding me to your server!\n\n"
                        "Run `/help` to see every available command."
                    ),
                    color=0x7B2FBE,
                )
                embed.set_footer(text="Yoran • Yoran Studios")
                await channel.send(embed=embed)
                break


async def main():
    async with Yoran() as bot:
        await bot.start(os.getenv("TOKEN"))

asyncio.run(main())
