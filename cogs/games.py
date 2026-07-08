import json
import os
import re

import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR, WARNING, INFO, GOLD
from utils import is_owner

GAMES_FILE = "data/games.json"

STATUS_CHOICES = ["In Development", "Coming Soon", "Beta", "Released"]
STATUS_META = {
    "In Development": ("🔧", WARNING),
    "Coming Soon":    ("🔜", INFO),
    "Beta":           ("🧪", GOLD),
    "Released":       ("🚀", SUCCESS),
}


def _load() -> dict:
    if not os.path.exists(GAMES_FILE):
        return {}
    with open(GAMES_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(GAMES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _guild_games(data: dict, guild_id: int) -> dict:
    return data.get(str(guild_id), {})


def _status_meta(status: str):
    return STATUS_META.get(status, ("🎮", PRIMARY))


# ── Owner-only management panel ────────────────────────────────────────────────

class AddGameModal(discord.ui.Modal, title="➕ Add New Game"):
    name = discord.ui.TextInput(label="Name", max_length=100)
    status = discord.ui.TextInput(
        label="Status",
        placeholder="In Development / Coming Soon / Beta / Released",
        max_length=20,
    )
    description = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000)
    image_url = discord.ui.TextInput(label="Banner/logo image URL (optional)", max_length=500, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        status_input = self.status.value.strip()
        status = next((s for s in STATUS_CHOICES if s.lower() == status_input.lower()), None)
        if not status:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Invalid status `{status_input}`. Valid options: " + ", ".join(f"`{s}`" for s in STATUS_CHOICES),
                    color=ERROR,
                ),
                ephemeral=True,
            )

        data = _load()
        games = data.setdefault(str(interaction.guild.id), {})
        gid = _slug(self.name.value)

        if gid in games:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ A game named **{self.name.value}** already exists.", color=ERROR),
                ephemeral=True,
            )

        role = await interaction.guild.create_role(
            name=f"🔔 {self.name.value}",
            mentionable=True,
            reason=f"Notify role for game '{self.name.value}' created by {interaction.user}",
        )

        games[gid] = {
            "name": self.name.value,
            "status": status,
            "description": self.description.value,
            "image_url": self.image_url.value or None,
            "role_id": role.id,
        }
        _save(data)

        emoji, color = _status_meta(status)
        embed = discord.Embed(title=f"{emoji}  {self.name.value}", description=self.description.value, color=color)
        embed.add_field(name="📊  Status", value=status, inline=True)
        embed.add_field(name="🔔  Notify Role", value=role.mention, inline=True)
        if self.image_url.value and self.image_url.value.startswith("http"):
            embed.set_thumbnail(url=self.image_url.value)
        embed.set_footer(text="Yoran Studios  •  Game registered")
        await interaction.response.send_message(embed=embed)


class GameAnnounceModal(discord.ui.Modal, title="📢 Game Announcement"):
    ann_title = discord.ui.TextInput(label="Title", max_length=100)
    content   = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=2000)
    image_url = discord.ui.TextInput(label="Image URL (optional)", max_length=500, required=False)

    def __init__(self, channel: discord.abc.Messageable, game_info: dict, role: discord.Role | None):
        super().__init__()
        self.channel = channel
        self.game_info = game_info
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        emoji, color = _status_meta(self.game_info["status"])
        embed = discord.Embed(
            title=f"{emoji}  {self.game_info['name']}  —  {self.ann_title.value}",
            description=self.content.value,
            color=color,
        )
        if self.image_url.value and self.image_url.value.startswith("http"):
            embed.set_image(url=self.image_url.value)
        embed.set_footer(text=f"{interaction.guild.name}  •  Yoran Studios", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.timestamp = discord.utils.utcnow()

        content = self.role.mention if self.role else None
        await self.channel.send(content=content, embed=embed)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Announcement sent to {self.channel.mention}", color=SUCCESS),
            ephemeral=True,
        )


class GameRemoveSelect(discord.ui.Select):
    def __init__(self, games: dict):
        options = [
            discord.SelectOption(label=g["name"], value=gid, description=g["status"], emoji=_status_meta(g["status"])[0])
            for gid, g in list(games.items())[:25]
        ]
        super().__init__(placeholder="Choose a game to remove...", options=options)

    async def callback(self, interaction: discord.Interaction):
        data = _load()
        games = _guild_games(data, interaction.guild.id)
        info = games.pop(self.values[0], None)
        if not info:
            return await interaction.response.edit_message(
                embed=discord.Embed(description="❌ Game not found (already removed?).", color=ERROR), view=None
            )
        _save(data)

        role = interaction.guild.get_role(info.get("role_id"))
        if role:
            try:
                await role.delete(reason=f"Game '{info['name']}' removed by {interaction.user}")
            except discord.HTTPException:
                pass

        await interaction.response.edit_message(
            embed=discord.Embed(description=f"✅ **{info['name']}** has been removed.", color=SUCCESS), view=None
        )


class GameAnnounceSelect(discord.ui.Select):
    def __init__(self, games: dict):
        options = [
            discord.SelectOption(label=g["name"], value=gid, description=g["status"], emoji=_status_meta(g["status"])[0])
            for gid, g in list(games.items())[:25]
        ]
        super().__init__(placeholder="Choose a game to announce for...", options=options)

    async def callback(self, interaction: discord.Interaction):
        data = _load()
        games = _guild_games(data, interaction.guild.id)
        info = games.get(self.values[0])
        if not info:
            return await interaction.response.edit_message(
                embed=discord.Embed(description="❌ Game not found.", color=ERROR), view=None
            )
        view = discord.ui.View(timeout=120)
        view.add_item(GameAnnounceChannelSelect(info))
        await interaction.response.edit_message(
            embed=discord.Embed(description=f"Pick the channel to announce **{info['name']}** news in.", color=PRIMARY),
            view=view,
        )


class GameAnnounceChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, game_info: dict):
        super().__init__(placeholder="Choose a channel...", channel_types=[discord.ChannelType.text])
        self.game_info = game_info

    async def callback(self, interaction: discord.Interaction):
        raw = self.values[0]
        channel = raw.resolve() or interaction.guild.get_channel(raw.id) or await raw.fetch()
        role = interaction.guild.get_role(self.game_info.get("role_id"))
        await interaction.response.send_modal(GameAnnounceModal(channel, self.game_info, role))


class GamePanelView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ This panel isn't yours — run `/gamepanel` yourself.", color=ERROR),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Add Game", emoji="➕", style=discord.ButtonStyle.success)
    async def add_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddGameModal())

    @discord.ui.button(label="Remove Game", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def remove_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = _load()
        games = _guild_games(data, interaction.guild.id)
        if not games:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ There are no games registered yet.", color=ERROR), ephemeral=True
            )
        view = discord.ui.View(timeout=120)
        view.add_item(GameRemoveSelect(games))
        await interaction.response.send_message(embed=discord.Embed(description="Select a game to remove.", color=WARNING), view=view, ephemeral=True)

    @discord.ui.button(label="Announce Update", emoji="📢", style=discord.ButtonStyle.primary)
    async def announce_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = _load()
        games = _guild_games(data, interaction.guild.id)
        if not games:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ There are no games registered yet.", color=ERROR), ephemeral=True
            )
        view = discord.ui.View(timeout=120)
        view.add_item(GameAnnounceSelect(games))
        await interaction.response.send_message(embed=discord.Embed(description="Select a game to announce news for.", color=PRIMARY), view=view, ephemeral=True)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have the required role for this command.", color=ERROR),
                ephemeral=True,
            )

    async def _game_autocomplete(self, interaction: discord.Interaction, current: str):
        data = _load()
        games = _guild_games(data, interaction.guild.id)
        choices = [
            app_commands.Choice(name=g["name"], value=gid)
            for gid, g in games.items()
            if current.lower() in g["name"].lower()
        ]
        return choices[:25]

    @app_commands.command(name="gamepanel", description="Open the game management panel (Owner only)")
    @app_commands.default_permissions(administrator=True)
    @is_owner()
    async def gamepanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎮  Game Management Panel",
            description=(
                "> ➕ **Add Game** — register a new Yoran Studios game and create its notify role\n"
                "> 🗑️ **Remove Game** — delete a game and its notify role\n"
                "> 📢 **Announce Update** — post news about a game, pinging its notify role"
            ),
            color=PRIMARY,
        )
        embed.set_footer(text="Yoran Studios  •  Owner tools")
        await interaction.response.send_message(embed=embed, view=GamePanelView(interaction.user.id), ephemeral=True)

    @app_commands.command(name="games", description="List all Yoran Studios games")
    async def games_list(self, interaction: discord.Interaction):
        data = _load()
        games = _guild_games(data, interaction.guild.id)

        embed = discord.Embed(title="🎮  Yoran Studios — Games", color=PRIMARY)
        if not games:
            embed.description = "No games have been announced yet. Stay tuned!"
        else:
            embed.description = "Use `/notify` to get pinged when there's news about a specific game."
            for g in games.values():
                emoji, _ = _status_meta(g["status"])
                embed.add_field(name=f"{emoji}  {g['name']}  •  {g['status']}", value=g["description"], inline=False)
        embed.set_footer(text="Yoran Studios", icon_url=self.bot.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gameinfo", description="View detailed info about a game")
    @app_commands.describe(game="Game to look up")
    @app_commands.autocomplete(game=_game_autocomplete)
    async def gameinfo(self, interaction: discord.Interaction, game: str):
        data = _load()
        games = _guild_games(data, interaction.guild.id)
        info = games.get(game)
        if not info:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Game not found.", color=ERROR), ephemeral=True
            )

        emoji, color = _status_meta(info["status"])
        role = interaction.guild.get_role(info.get("role_id"))
        embed = discord.Embed(title=f"{emoji}  {info['name']}", description=info["description"], color=color)
        embed.add_field(name="📊  Status", value=info["status"], inline=True)
        embed.add_field(name="🔔  Notify Role", value=role.mention if role else "—", inline=True)
        if info.get("image_url"):
            embed.set_image(url=info["image_url"])
        embed.set_footer(text="Use /notify to get pinged about this game")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="notify", description="Toggle the notify role for a game")
    @app_commands.describe(game="Game you want to be notified about")
    @app_commands.autocomplete(game=_game_autocomplete)
    async def notify(self, interaction: discord.Interaction, game: str):
        data = _load()
        games = _guild_games(data, interaction.guild.id)
        info = games.get(game)
        if not info:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Game not found.", color=ERROR), ephemeral=True
            )

        role = interaction.guild.get_role(info.get("role_id"))
        if not role:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Notify role for this game no longer exists.", color=ERROR),
                ephemeral=True,
            )

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Game notify toggle")
            desc = f"🔕 You will no longer be notified about **{info['name']}**."
        else:
            await interaction.user.add_roles(role, reason="Game notify toggle")
            desc = f"🔔 You'll now be notified about **{info['name']}**!"

        await interaction.response.send_message(embed=discord.Embed(description=desc, color=SUCCESS), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))
