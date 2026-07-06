import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR
from utils import is_admin


def _icon(guild: discord.Guild) -> str | None:
    return guild.icon.url if guild.icon else None


def _set_image(embed: discord.Embed, url: str | None):
    if url and url.startswith("http"):
        embed.set_image(url=url)


def _set_thumbnail(embed: discord.Embed, url: str | None):
    if url and url.startswith("http"):
        embed.set_thumbnail(url=url)


# ── Modals ────────────────────────────────────────────────────────────────────

class AnnounceModal(discord.ui.Modal, title="📢 Make an Announcement"):
    ann_title = discord.ui.TextInput(label="Title", max_length=100)
    content   = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=2000)
    image_url = discord.ui.TextInput(
        label="Banner Image URL (optional)",
        placeholder="https://i.imgur.com/... or Discord image link",
        max_length=500,
        required=False,
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=f"📢  {self.ann_title.value}", description=self.content.value, color=PRIMARY)
        _set_image(embed, self.image_url.value)
        embed.set_footer(
            text=f"{interaction.guild.name}  •  Announced by {interaction.user.display_name}",
            icon_url=_icon(interaction.guild),
        )
        embed.timestamp = discord.utils.utcnow()
        await self.channel.send(embed=embed)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Announcement sent to {self.channel.mention}", color=SUCCESS),
            ephemeral=True,
        )


class EmbedModal(discord.ui.Modal, title="📝 Custom Embed"):
    emb_title     = discord.ui.TextInput(label="Title", max_length=200)
    description   = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=2000)
    color_hex     = discord.ui.TextInput(label="Color hex (optional)", placeholder="e.g. 7B2FBE", max_length=6, required=False)
    image_url     = discord.ui.TextInput(
        label="Image URL (optional)",
        placeholder="https://i.imgur.com/... — appears as large banner",
        max_length=500,
        required=False,
    )
    thumbnail_url = discord.ui.TextInput(
        label="Thumbnail URL (optional)",
        placeholder="https://i.imgur.com/... — appears as small icon top-right",
        max_length=500,
        required=False,
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int(self.color_hex.value, 16) if self.color_hex.value else PRIMARY
        except ValueError:
            color = PRIMARY
        embed = discord.Embed(title=self.emb_title.value, description=self.description.value, color=color)
        _set_image(embed, self.image_url.value)
        _set_thumbnail(embed, self.thumbnail_url.value)
        embed.timestamp = discord.utils.utcnow()
        await self.channel.send(embed=embed)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Embed sent to {self.channel.mention}", color=SUCCESS),
            ephemeral=True,
        )


# ── Cog ───────────────────────────────────────────────────────────────────────

class Announcements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have the required role for this command.", color=ERROR),
                ephemeral=True,
            )

    @app_commands.command(name="announce", description="Send an announcement to a channel")
    @app_commands.describe(channel="Channel to announce in")
    @is_admin()
    async def announce(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.send_modal(AnnounceModal(channel))

    @app_commands.command(name="embed", description="Send a custom embed to a channel")
    @app_commands.describe(channel="Channel to post in")
    @is_admin()
    async def embed_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.send_modal(EmbedModal(channel))


async def setup(bot: commands.Bot):
    await bot.add_cog(Announcements(bot))
