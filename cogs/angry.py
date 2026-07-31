import discord
from discord.ext import commands

ANGRY_CHANNEL_ID = 1532796151131148339
ANGRY_EMOJI_ID = 1525140908066996314
ANGRY_EMOJI = "<:Angry:1525140908066996314>"


def _is_only_angry(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    token = f"<:Angry:{ANGRY_EMOJI_ID}>"
    animated_token = f"<a:Angry:{ANGRY_EMOJI_ID}>"
    remaining = stripped.replace(token, "").replace(animated_token, "").strip()
    return remaining == "" and (token in stripped or animated_token in stripped)


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
        if not _is_only_angry(message.content) or message.attachments:
            try:
                await message.delete()
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Angry(bot))
