import re

import discord
from discord.ext import commands

ANGRY_CHANNEL_ID = 1532796151131148339
ANGRY_EMOJI_ID = 1525140908066996314

_EMOJI_RE = re.compile(r"<a?:\w+:(\d+)>")


def _is_only_angry(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    matches = _EMOJI_RE.findall(stripped)
    if not matches:
        return False
    if any(m != str(ANGRY_EMOJI_ID) for m in matches):
        return False
    leftover = _EMOJI_RE.sub("", stripped).strip()
    return leftover == ""


class Angry(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id != ANGRY_CHANNEL_ID:
            return
        if message.author.guild_permissions.administrator:
            return
        if message.attachments or message.stickers or not _is_only_angry(message.content):
            try:
                await message.delete()
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Angry(bot))
