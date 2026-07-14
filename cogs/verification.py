import json
import os

import discord
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR
import storage

MEMBER_ROLE_NAME = "Member"
UNVERIFIED_ROLE_NAME = "Unverified"

STUDIOS_GUILD_ID = 1523445628204482620

# The first N members to verify get the VIP role — after that, nobody else.
VIP_ROLE_ID = 1526499976421703731
VIP_LIMIT = 100
VIP_FILE = storage.path("vip.json")

# Members who are ALSO in the legacy (destroy) server get the OG badge.
OG_ROLE_NAME = "OG"


def _load_vip() -> dict:
    if not os.path.exists(VIP_FILE):
        return {"granted": []}
    try:
        with open(VIP_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"granted": []}


def _save_vip(data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(VIP_FILE, "w") as f:
        json.dump(data, f, indent=2)


class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _grant_extras(self, interaction: discord.Interaction, member: discord.Member) -> list[str]:
        """VIP for the first 100 verified members + OG for legacy-server members."""
        guild = interaction.guild
        extras: list[str] = []

        # VIP — first VIP_LIMIT verified members only
        data = _load_vip()
        granted = data.setdefault("granted", [])
        if str(member.id) not in granted and len(granted) < VIP_LIMIT:
            vip = guild.get_role(VIP_ROLE_ID)
            if vip:
                try:
                    await member.add_roles(vip, reason=f"VIP — verified member #{len(granted) + 1}")
                    granted.append(str(member.id))
                    _save_vip(data)
                    extras.append(vip.name)
                except discord.HTTPException:
                    pass

        # OG — member of the legacy server too
        legacy = next((g for g in interaction.client.guilds if g.id != STUDIOS_GUILD_ID), None)
        if legacy and legacy.get_member(member.id):
            og = discord.utils.get(guild.roles, name=OG_ROLE_NAME)
            if og is None:
                try:
                    og = await guild.create_role(
                        name=OG_ROLE_NAME,
                        colour=discord.Colour.from_rgb(230, 126, 34),
                        mentionable=False,
                        reason="OG badge for legacy-server members",
                    )
                except discord.HTTPException:
                    og = None
            if og and og not in member.roles:
                try:
                    await member.add_roles(og, reason="OG — also in the legacy server")
                    extras.append(og.name)
                except discord.HTTPException:
                    pass

        return extras

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="✅", custom_id="yoran:verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        member_role = discord.utils.get(guild.roles, name=MEMBER_ROLE_NAME)
        unverified_role = discord.utils.get(guild.roles, name=UNVERIFIED_ROLE_NAME)

        if member_role and member_role in member.roles:
            return await interaction.response.send_message(
                embed=discord.Embed(description="✅ You are already verified!", color=SUCCESS), ephemeral=True
            )
        try:
            if member_role:
                await member.add_roles(member_role, reason="Verification")
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="Verification")

            extras = await self._grant_extras(interaction, member)

            description = (
                f"Welcome to **{guild.name}**!\n\n"
                "> You now have full access to the server.\n"
                "> Check out our upcoming games, join the community, and enjoy your stay!"
            )
            if extras:
                description += "\n\n🎁 You also unlocked: " + ", ".join(f"**{name}**" for name in extras)

            embed = discord.Embed(title="✅  Verified!", description=description, color=SUCCESS)
            embed.set_footer(text=f"{guild.name}  •  Yoran Verification")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ I'm missing permissions to assign roles. Please contact staff.", color=ERROR),
                ephemeral=True,
            )


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(VerificationView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
