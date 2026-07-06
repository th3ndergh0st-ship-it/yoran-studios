import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import SUCCESS, ERROR, WARNING, GOLD, PRIMARY
from utils import is_admin
import economy_data as econ

DAILY_MIN, DAILY_MAX = 100, 250
WORK_MIN, WORK_MAX = 50, 150
DAILY_COOLDOWN = 86400
WORK_COOLDOWN = 3600

WORK_FLAVORS = [
    "You helped playtest a build and squashed a couple of bugs",
    "You modeled a prop for an upcoming Yoran Studios game",
    "You wrote a Lua script for the dev team",
    "You moderated the community chat like a champ",
    "You clipped a gameplay highlight for social media",
    "You reported a detailed bug and got a bounty",
    "You helped a newcomer in #general",
    "You brainstormed ideas in a suggestions thread",
]


def _fmt(amount: int) -> str:
    return f"{econ.CURRENCY_EMOJI} `{amount:,}` {econ.CURRENCY_NAME}"


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have the required role for this command.", color=ERROR),
                ephemeral=True,
            )

    @app_commands.command(name="balance", description="Check your (or someone else's) balance")
    @app_commands.describe(member="Member to check")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        bal = econ.get_balance(interaction.guild.id, target.id)
        embed = discord.Embed(title=f"💰  {target.display_name}'s Balance", description=_fmt(bal), color=GOLD)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily reward")
    async def daily(self, interaction: discord.Interaction):
        last = econ.get_cooldown(interaction.guild.id, interaction.user.id, "last_daily")
        now = time.time()
        remaining = DAILY_COOLDOWN - (now - last)
        if remaining > 0:
            h, m = divmod(int(remaining // 60), 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ You already claimed your daily reward. Try again in **{h}h {m}m**.", color=WARNING),
                ephemeral=True,
            )
        amount = random.randint(DAILY_MIN, DAILY_MAX)
        new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_daily", now)
        embed = discord.Embed(
            title="🎁  Daily Reward Claimed!",
            description=f"You received {_fmt(amount)}!\nNew balance: {_fmt(new_bal)}",
            color=SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="work", description="Work to earn some coins")
    async def work(self, interaction: discord.Interaction):
        last = econ.get_cooldown(interaction.guild.id, interaction.user.id, "last_work")
        now = time.time()
        remaining = WORK_COOLDOWN - (now - last)
        if remaining > 0:
            m = int(remaining // 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ You're tired. Rest for **{m}m** before working again.", color=WARNING),
                ephemeral=True,
            )
        amount = random.randint(WORK_MIN, WORK_MAX)
        flavor = random.choice(WORK_FLAVORS)
        new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_work", now)
        embed = discord.Embed(
            title="🛠️  Work Complete",
            description=f"{flavor} and earned {_fmt(amount)}!\nNew balance: {_fmt(new_bal)}",
            color=SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pay", description="Send coins to another member")
    @app_commands.describe(member="Member to pay", amount="Amount to send")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]):
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You can't pay yourself.", color=ERROR), ephemeral=True
            )
        if member.bot:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You can't pay a bot.", color=ERROR), ephemeral=True
            )
        bal = econ.get_balance(interaction.guild.id, interaction.user.id)
        if bal < amount:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You don't have enough coins. Your balance: {_fmt(bal)}", color=ERROR),
                ephemeral=True,
            )
        econ.add_balance(interaction.guild.id, interaction.user.id, -amount)
        econ.add_balance(interaction.guild.id, member.id, amount)
        embed = discord.Embed(
            description=f"✅ {interaction.user.mention} sent {_fmt(amount)} to {member.mention}!",
            color=SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="View the richest members in this server")
    async def leaderboard(self, interaction: discord.Interaction):
        top = econ.get_leaderboard(interaction.guild.id, 10)
        embed = discord.Embed(title="🏆  Coin Leaderboard", color=GOLD)
        if not top:
            embed.description = "No one has earned any coins yet."
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, (uid, bal) in enumerate(top):
                member = interaction.guild.get_member(int(uid))
                name = member.mention if member else f"<@{uid}>"
                prefix = medals[i] if i < 3 else f"`#{i + 1}`"
                lines.append(f"{prefix}  {name} — {_fmt(bal)}")
            embed.description = "\n".join(lines)
        embed.set_footer(text="Yoran Studios  •  Economy")
        await interaction.response.send_message(embed=embed)

    shop = app_commands.Group(name="shop", description="Coin shop commands")

    @shop.command(name="view", description="View items available in the coin shop")
    async def shop_view(self, interaction: discord.Interaction):
        items = econ.get_shop_items(interaction.guild.id)
        embed = discord.Embed(title="🛒  Coin Shop", color=PRIMARY)
        if not items:
            embed.description = "The shop is empty right now."
        else:
            for item in items:
                role = interaction.guild.get_role(item["role_id"])
                embed.add_field(
                    name=item["name"],
                    value=f"{_fmt(item['price'])}\nGrants: {role.mention if role else '—'}",
                    inline=True,
                )
            embed.set_footer(text="Use /shop buy <item> to purchase")
        await interaction.response.send_message(embed=embed)

    @shop.command(name="buy", description="Buy an item from the coin shop")
    @app_commands.describe(name="Name of the item to buy")
    async def shop_buy(self, interaction: discord.Interaction, name: str):
        items = econ.get_shop_items(interaction.guild.id)
        item = next((i for i in items if i["name"].lower() == name.lower()), None)
        if not item:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Item not found in the shop.", color=ERROR), ephemeral=True
            )
        role = interaction.guild.get_role(item["role_id"])
        if role and role in interaction.user.roles:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You already own this item.", color=ERROR), ephemeral=True
            )
        bal = econ.get_balance(interaction.guild.id, interaction.user.id)
        if bal < item["price"]:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Not enough coins. You need {_fmt(item['price'])}, you have {_fmt(bal)}.", color=ERROR),
                ephemeral=True,
            )
        econ.add_balance(interaction.guild.id, interaction.user.id, -item["price"])
        if role:
            await interaction.user.add_roles(role, reason="Coin shop purchase")
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ You bought **{item['name']}**!", color=SUCCESS)
        )

    @shop.command(name="additem", description="Add an item to the coin shop (admin)")
    @app_commands.describe(name="Item name", price="Price in coins", role="Role granted when purchased")
    @is_admin()
    async def shop_additem(self, interaction: discord.Interaction, name: str, price: app_commands.Range[int, 1, 1_000_000], role: discord.Role):
        econ.add_shop_item(interaction.guild.id, name, price, role.id)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Added **{name}** ({_fmt(price)}) → {role.mention} to the shop.", color=SUCCESS)
        )

    @shop.command(name="removeitem", description="Remove an item from the coin shop (admin)")
    @app_commands.describe(name="Item name to remove")
    @is_admin()
    async def shop_removeitem(self, interaction: discord.Interaction, name: str):
        removed = econ.remove_shop_item(interaction.guild.id, name)
        if not removed:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Item not found.", color=ERROR), ephemeral=True
            )
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Removed **{name}** from the shop.", color=SUCCESS)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
