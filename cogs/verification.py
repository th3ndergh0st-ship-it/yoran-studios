import discord
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR

MEMBER_ROLE_NAME = "Member"
UNVERIFIED_ROLE_NAME = "Unverified"


class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

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
            embed = discord.Embed(
                title="✅  Verified!",
                description=(
                    f"Welcome to **{guild.name}**!\n\n"
                    "> You now have full access to the server.\n"
                    "> Check out our upcoming games, join the community, and enjoy your stay!"
                ),
                color=SUCCESS,
            )
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
