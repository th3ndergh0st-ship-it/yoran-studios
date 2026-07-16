import json
import os
import random
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import SUCCESS, ERROR, WARNING, GOLD
from utils import is_mod
import storage

GIVEAWAYS_FILE = storage.path("giveaways.json")
ENDED_COLOR    = 0x747f8d


def _load() -> dict:
    if not os.path.exists(GIVEAWAYS_FILE):
        return {}
    with open(GIVEAWAYS_FILE) as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(GIVEAWAYS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _parse_duration(s: str) -> int | None:
    matches = re.findall(r"(\d+)\s*([dhms])", s.lower())
    if not matches:
        return None
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    total = sum(int(v) * units[u] for v, u in matches)
    return total or None


def _active_embed(prize: str, host_id: int, ends_at: datetime, winners: int, entries: int) -> discord.Embed:
    embed = discord.Embed(title=f"🎉  {prize}", color=GOLD)
    embed.add_field(name="⏰  Ends", value=discord.utils.format_dt(ends_at, "R"), inline=True)
    embed.add_field(name="🏆  Winners", value=f"`{winners}`", inline=True)
    embed.add_field(name="📋  Entries", value=f"`{entries}`", inline=True)
    embed.add_field(name="ℹ️  How to enter", value="Press **🎉** below to join!", inline=False)
    embed.set_footer(text=f"Hosted by user {host_id}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _ended_embed(prize: str, winner_mentions: list[str]) -> discord.Embed:
    desc = ("🏆 **Winner(s):** " + ", ".join(winner_mentions)) if winner_mentions else "❌ No valid entries — no winner selected."
    embed = discord.Embed(title=f"🎉  {prize}", description=desc, color=ENDED_COLOR)
    embed.set_footer(text="Giveaway ended")
    embed.timestamp = discord.utils.utcnow()
    return embed


class GiveawayEnterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎉  Enter Giveaway", style=discord.ButtonStyle.primary, custom_id="yoran:giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        data   = _load()
        msg_id = str(interaction.message.id)

        if msg_id not in data or data[msg_id].get("ended"):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ This giveaway has already ended.", color=ERROR),
                ephemeral=True,
            )

        gw      = data[msg_id]
        user_id = str(interaction.user.id)
        entries = gw.setdefault("entries", [])

        if user_id in entries:
            entries.remove(user_id)
            reply_text  = "❌ You have **left** the giveaway."
            reply_color = WARNING
        else:
            entries.append(user_id)
            reply_text  = "✅ You've **entered** the giveaway! Good luck! 🍀"
            reply_color = SUCCESS

        _save(data)

        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if "Entries" in field.name:
                embed.set_field_at(i, name=field.name, value=f"`{len(entries)}`", inline=True)
                break

        await interaction.response.edit_message(embed=embed)
        await interaction.followup.send(
            embed=discord.Embed(description=reply_text, color=reply_color),
            ephemeral=True,
        )


class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(GiveawayEnterView())
        self.check_giveaways.start()

    async def cog_unload(self):
        self.check_giveaways.cancel()


    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        data = _load()
        now  = datetime.now(tz=timezone.utc).timestamp()
        changed = False

        for msg_id, gw in list(data.items()):
            if gw.get("ended"):
                continue
            if now < gw["ends_at"]:
                continue

            await self._end_giveaway(msg_id, gw, data)
            changed = True

        if changed:
            _save(data)

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


    async def _end_giveaway(self, msg_id: str, gw: dict, data: dict):
        channel = self.bot.get_channel(gw["channel_id"])
        if not channel:
            gw["ended"] = True
            return

        try:
            message = await channel.fetch_message(int(msg_id))
        except discord.NotFound:
            gw["ended"] = True
            return

        entries  = gw.get("entries", [])
        n        = gw["winner_count"]
        prize    = gw["prize"]
        pool     = list(set(entries))
        winners  = random.sample(pool, min(n, len(pool))) if pool else []
        mentions = [f"<@{uid}>" for uid in winners]

        await message.edit(embed=_ended_embed(prize, mentions), view=None)

        if winners:
            await channel.send(
                content=" ".join(mentions),
                embed=discord.Embed(
                    title="🎊  Congratulations!",
                    description=f"You won **{prize}**!\nContact staff to claim your prize.",
                    color=SUCCESS,
                ),
            )
        else:
            await channel.send(
                embed=discord.Embed(
                    description=f"❌ Giveaway for **{prize}** ended with no valid entries.",
                    color=ERROR,
                )
            )

        gw["ended"]   = True
        gw["winners"] = winners
        data[msg_id]  = gw


    giveaway = app_commands.Group(
        name="giveaway",
        description="Giveaway commands",
        default_permissions=discord.Permissions(manage_messages=True),
    )

    @giveaway.command(name="start", description="Start a giveaway")
    @app_commands.describe(
        channel  = "Channel to post the giveaway in",
        prize    = "What are you giving away?",
        duration = "Duration: e.g. 1h, 30m, 2d, 1h30m",
        winners  = "Number of winners (default: 1)",
    )
    @is_mod()
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        prize: str,
        duration: str,
        winners: app_commands.Range[int, 1, 20] = 1,
    ):
        seconds = _parse_duration(duration)
        if not seconds:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ Invalid duration. Use formats like `1h`, `30m`, `2d`, `1h30m`.",
                    color=ERROR,
                ),
                ephemeral=True,
            )

        ends_at = datetime.now(tz=timezone.utc).timestamp() + seconds
        ends_dt = datetime.fromtimestamp(ends_at, tz=timezone.utc)

        embed = _active_embed(prize, interaction.user.id, ends_dt, winners, 0)
        msg   = await channel.send(embed=embed, view=GiveawayEnterView())

        data = _load()
        data[str(msg.id)] = {
            "channel_id":   channel.id,
            "guild_id":     interaction.guild.id,
            "prize":        prize,
            "winner_count": winners,
            "ends_at":      ends_at,
            "host":         interaction.user.id,
            "entries":      [],
            "ended":        False,
        }
        _save(data)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Giveaway started in {channel.mention}!\nEnds {discord.utils.format_dt(ends_dt, 'R')}.",
                color=SUCCESS,
            ),
            ephemeral=True,
        )

    @giveaway.command(name="end", description="End a giveaway early")
    @app_commands.describe(message_id="ID of the giveaway message")
    @is_mod()
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        data   = _load()
        msg_id = message_id.strip()

        if msg_id not in data:
            return await interaction.followup.send(
                embed=discord.Embed(description="❌ Giveaway not found. Check the message ID.", color=ERROR),
                ephemeral=True,
            )
        if data[msg_id].get("ended"):
            return await interaction.followup.send(
                embed=discord.Embed(description="❌ That giveaway has already ended.", color=ERROR),
                ephemeral=True,
            )

        await self._end_giveaway(msg_id, data[msg_id], data)
        _save(data)

        await interaction.followup.send(
            embed=discord.Embed(description="✅ Giveaway ended and winner(s) selected.", color=SUCCESS),
            ephemeral=True,
        )

    @giveaway.command(name="reroll", description="Reroll the winner of an ended giveaway")
    @app_commands.describe(message_id="ID of the giveaway message")
    @is_mod()
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        data   = _load()
        msg_id = message_id.strip()

        if msg_id not in data:
            return await interaction.followup.send(
                embed=discord.Embed(description="❌ Giveaway not found.", color=ERROR),
                ephemeral=True,
            )

        gw      = data[msg_id]
        entries = list(set(gw.get("entries", [])))
        n       = gw["winner_count"]
        prize   = gw["prize"]

        if not entries:
            return await interaction.followup.send(
                embed=discord.Embed(description="❌ No entries to reroll from.", color=ERROR),
                ephemeral=True,
            )

        winners  = random.sample(entries, min(n, len(entries)))
        mentions = [f"<@{uid}>" for uid in winners]

        channel = self.bot.get_channel(gw["channel_id"])
        if channel:
            await channel.send(
                content=" ".join(mentions),
                embed=discord.Embed(
                    title="🎲  Reroll — New Winner!",
                    description=f"Congratulations! You won **{prize}**!\nContact staff to claim your prize.",
                    color=GOLD,
                ),
            )

        gw["winners"] = winners
        _save(data)

        await interaction.followup.send(
            embed=discord.Embed(description=f"✅ Rerolled! New winner(s): {', '.join(mentions)}", color=SUCCESS),
            ephemeral=True,
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = "❌ You don't have the required role for this command."
        else:
            print(f"[Yoran] Command error in {getattr(interaction.command, 'qualified_name', '?')}: {error!r}", flush=True)
            msg = "❌ Something went wrong running that command — the error was logged."
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description=msg, color=ERROR),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))
