import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR
from utils import is_owner


class RoleTools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have the required role for this command.", color=ERROR),
                ephemeral=True,
            )

    @app_commands.command(
        name="organizeroles",
        description="Reorder this server's roles to match another server's hierarchy (Owner only)",
    )
    @app_commands.describe(source_id="ID of the server whose role order to copy (the bot must be in it)")
    @is_owner()
    async def organizeroles(self, interaction: discord.Interaction, source_id: str):
        guild = interaction.guild
        try:
            source = self.bot.get_guild(int(source_id))
        except ValueError:
            source = None
        if source is None:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ I'm not in that server (or the ID is invalid).", color=ERROR),
                ephemeral=True,
            )
        if source.id == guild.id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Source and current server are the same.", color=ERROR),
                ephemeral=True,
            )

        await interaction.response.defer()

        # Roles here that the bot is allowed to move (below its own top role).
        movable = [r for r in guild.roles if not r.is_default() and not r.managed and r < guild.me.top_role]
        by_name: dict[str, list[discord.Role]] = {}
        for r in movable:
            by_name.setdefault(r.name, []).append(r)

        # Source hierarchy from lowest to highest, matched to our roles by name.
        source_order = sorted(
            (r for r in source.roles if not r.is_default() and not r.managed),
            key=lambda r: r.position,
        )
        positions: dict[discord.Role, int] = {}
        pos = 1
        for src_role in source_order:
            candidates = by_name.get(src_role.name)
            if candidates:
                positions[candidates.pop(0)] = pos
                pos += 1

        if not positions:
            return await interaction.followup.send(
                embed=discord.Embed(
                    description=f"❌ No role names here match roles in **{source.name}** — nothing to reorder.",
                    color=ERROR,
                )
            )

        try:
            await guild.edit_role_positions(positions=positions, reason=f"Role order synced from {source.name} by {interaction.user}")
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"❌ Discord rejected the reorder: `{e}`", color=ERROR)
            )

        unmatched = [r.name for lst in by_name.values() for r in lst]
        embed = discord.Embed(
            title="🎭  Roles Organized",
            description=f"Reordered **{len(positions)}** roles to match the hierarchy of **{source.name}**.",
            color=SUCCESS,
        )
        if unmatched:
            embed.add_field(
                name="⚠️ Not in source (left as-is)",
                value=", ".join(f"`{n}`" for n in unmatched[:20]) + ("…" if len(unmatched) > 20 else ""),
                inline=False,
            )
        embed.set_footer(text="Tip: roles above my own top role can't be moved by me.")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleTools(bot))
