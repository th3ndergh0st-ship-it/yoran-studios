import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import os
from dotenv import load_dotenv
from keepalive import start_keepalive

load_dotenv()

# This bot is exclusive to the Yoran Studios server. Slash commands are
# refused everywhere else — the Yoran Shop server has its own separate bot.
STUDIOS_GUILD_ID = 1523445628204482620


class StudiosOnlyTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or interaction.guild.id == STUDIOS_GUILD_ID:
            return True
        await interaction.response.send_message(
            embed=discord.Embed(
                description="❌ This bot is exclusive to the **Yoran Studios** server.",
                color=0xE74C3C,
            ),
            ephemeral=True,
        )
        return False


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
            "cogs.setup",
            "cogs.games",
            "cogs.economy",
            "cogs.education",
            "cogs.roletools",
        ]
        for ext in extensions:
            await self.load_extension(ext)
        port = int(os.getenv("PORT", "3000"))
        start_keepalive(port=port)

    async def on_ready(self):
        synced = await self.tree.sync()
        print(f"[Yoran] Synced {len(synced)} slash commands", flush=True)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="/help • Yoran Studios",
            ),
            status=discord.Status.online,
        )
        print(f"[Yoran] Online · {self.user} · {len(self.guilds)} server(s)")

    async def on_member_join(self, member: discord.Member):
        if member.guild.id != STUDIOS_GUILD_ID:
            return
        role = discord.utils.get(member.guild.roles, name="🔒 Unverified")
        if role:
            await member.add_roles(role, reason="Auto-assigned on join")

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
