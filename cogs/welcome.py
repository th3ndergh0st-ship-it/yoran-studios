import discord
from discord.ext import commands
import json
import os

from config import PRIMARY, SUCCESS, ERROR


def _load() -> dict:
    if not os.path.exists("data/welcome.json"):
        return {}
    with open("data/welcome.json", "r") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs("data", exist_ok=True)
    with open("data/welcome.json", "w") as f:
        json.dump(data, f, indent=2)


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        data = _load()
        cfg = data.get(str(member.guild.id), {}).get("welcome")
        if not cfg:
            return
        channel = member.guild.get_channel(cfg["channel_id"])
        if not channel:
            return
        embed = discord.Embed(
            title=cfg.get("title", "Welcome!").replace("{user}", member.display_name).replace("{server}", member.guild.name),
            description=cfg.get("message", f"Welcome {member.mention}!").replace("{user}", member.mention).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count)),
            color=int(cfg.get("color", PRIMARY)),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{member.guild.name}  •  Member #{member.guild.member_count}", icon_url=member.guild.icon.url if member.guild.icon else None)
        embed.timestamp = discord.utils.utcnow()
        if cfg.get("banner"):
            embed.set_image(url=cfg["banner"])
        await channel.send(content=member.mention if cfg.get("ping") else None, embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        data = _load()
        cfg = data.get(str(member.guild.id), {}).get("goodbye")
        if not cfg:
            return
        channel = member.guild.get_channel(cfg["channel_id"])
        if not channel:
            return
        embed = discord.Embed(
            title=cfg.get("title", "Goodbye!").replace("{user}", member.display_name).replace("{server}", member.guild.name),
            description=cfg.get("message", f"**{member.display_name}** has left.").replace("{user}", str(member)).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count)),
            color=int(cfg.get("color", ERROR)),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{member.guild.name}  •  {member.guild.member_count} members remaining", icon_url=member.guild.icon.url if member.guild.icon else None)
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)



async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
