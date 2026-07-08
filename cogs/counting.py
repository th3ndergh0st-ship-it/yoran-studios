import json
import os

import discord
from discord.ext import commands

import economy_data as econ
import storage

COUNTING_FILE = storage.path("counting.json")

MILESTONE_EVERY = 50      # every N counts...
MILESTONE_REWARD = 100    # ...the counter earns this many coins


def _load() -> dict:
    if not os.path.exists(COUNTING_FILE):
        return {}
    with open(COUNTING_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(COUNTING_FILE, "w") as f:
        json.dump(data, f, indent=2)


class Counting(commands.Cog):
    """Classic counting game: members count up one number per message.
    Wrong number or counting twice in a row resets the chain to 1."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        data = _load()
        cfg = data.get(str(message.guild.id))
        if not cfg or message.channel.id != cfg.get("channel_id"):
            return

        content = message.content.strip()
        try:
            number = int(content)
        except ValueError:
            # keep the channel clean: non-numbers get removed silently
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        current = cfg.get("current", 0)
        last_user = cfg.get("last_user_id")

        if number == current + 1 and str(message.author.id) != last_user:
            cfg["current"] = number
            cfg["last_user_id"] = str(message.author.id)
            if number > cfg.get("high_score", 0):
                cfg["high_score"] = number
            _save(data)
            try:
                if number % MILESTONE_EVERY == 0:
                    await message.add_reaction("🎉")
                    econ.add_balance(message.guild.id, message.author.id, MILESTONE_REWARD)
                    await message.channel.send(
                        embed=discord.Embed(
                            description=(
                                f"🎉 **{number}!** Milestone reached — {message.author.mention} "
                                f"earned {econ.CURRENCY_EMOJI} `{MILESTONE_REWARD}` {econ.CURRENCY_NAME}!"
                            ),
                            color=0xF1C40F,
                        )
                    )
                else:
                    await message.add_reaction("✅")
            except discord.HTTPException:
                pass
        else:
            ruined_at = current
            cfg["current"] = 0
            cfg["last_user_id"] = None
            _save(data)
            try:
                await message.add_reaction("❌")
                if str(message.author.id) == last_user and number == current + 1:
                    why = "you can't count twice in a row"
                else:
                    why = f"the next number was **{current + 1}**"
                await message.channel.send(
                    embed=discord.Embed(
                        title="💥  RUINED!",
                        description=(
                            f"{message.author.mention} broke the chain at **{ruined_at}** ({why}).\n"
                            f"Back to **1**! High score: **{cfg.get('high_score', 0)}**"
                        ),
                        color=0xE74C3C,
                    )
                )
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Counting(bot))
