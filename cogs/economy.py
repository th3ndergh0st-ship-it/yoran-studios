import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import SUCCESS, ERROR, WARNING, GOLD, PRIMARY, INFO
from utils import is_admin
import economy_data as econ

DAILY_MIN, DAILY_MAX = 100, 250
WORK_MIN, WORK_MAX = 50, 150
DAILY_COOLDOWN = 86400
WORK_COOLDOWN = 3600
ROB_COOLDOWN = 7200
CRIME_COOLDOWN = 1800
BEG_COOLDOWN = 300

ROB_MIN_TARGET_BALANCE = 50
ROB_SUCCESS_CHANCE = 0.45
ROB_STEAL_PCT = (0.10, 0.35)
ROB_FINE_PCT = (0.05, 0.15)
ROB_FINE_MIN = 20

CRIME_SUCCESS_CHANCE = 0.6
CRIME_SUCCESS_RANGE = (100, 300)
CRIME_FAIL_RANGE = (50, 150)

BEG_RANGE = (5, 40)
BEG_NOTHING_CHANCE = 0.15

SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "💎", "7️⃣"]
SLOT_WEIGHTS = [35, 30, 20, 10, 5]
SLOT_TRIPLE_MULTIPLIER = {"🍒": 3, "🍋": 3, "🍊": 4, "💎": 6, "7️⃣": 10}

JOBS = {
    "Playtester":         {"min": 60, "max": 160, "flavor": "found bugs in the newest build"},
    "Scripter":            {"min": 90, "max": 220, "flavor": "shipped a new Lua script"},
    "3D Artist":           {"min": 80, "max": 200, "flavor": "modeled a prop for the next game"},
    "Community Manager":   {"min": 70, "max": 180, "flavor": "kept the community drama-free"},
    "Marketer":            {"min": 65, "max": 170, "flavor": "posted a trailer that went semi-viral"},
}

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

CRIME_SUCCESS_FLAVORS = [
    "You leaked a rival studio's trailer early and sold the clip",
    "You snuck into a private Discord and swiped some concept art",
    "You flipped a limited-time item for a tidy profit",
    "You sold a 'guaranteed win' strategy guide that actually worked",
]
CRIME_FAIL_FLAVORS = [
    "Got caught leaking the trailer — fined on the spot",
    "The concept art had a watermark. Busted.",
    "The trade got reported mid-flip. Ouch.",
    "Your strategy guide didn't work and everyone found out",
]

BEG_FLAVORS = [
    "A random NPC felt bad for you and tossed some coins",
    "You found loose change on the Yoran Studios office couch",
    "A generous dev tipped you for reporting a bug",
    "Someone in #general felt bad and sent you a few coins",
]
BEG_NOTHING_FLAVORS = [
    "Nobody had any spare coins for you",
    "You got ignored. Tough crowd.",
]

ROB_SUCCESS_FLAVORS = [
    "You snuck up on {target} and grabbed some coins before they noticed",
    "You pickpocketed {target} during a trivia night",
    "{target} left their wallet on the table. Rookie mistake.",
]
ROB_FAIL_FLAVORS = [
    "{target} caught you red-handed and you had to pay up",
    "Security footage caught you. Fined on the spot.",
    "You tripped an alarm trying to rob {target}",
]


def _fmt(amount: int) -> str:
    return f"{econ.CURRENCY_EMOJI} `{amount:,}` {econ.CURRENCY_NAME}"


def _cooldown_remaining(guild_id: int, user_id: int, key: str, cooldown: int) -> float:
    last = econ.get_cooldown(guild_id, user_id, key)
    return cooldown - (time.time() - last)


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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


    # ── Balance / bank ──────────────────────────────────────────────────────────

    @app_commands.command(name="balance", description="Check your (or someone else's) wallet and bank balance")
    @app_commands.describe(member="Member to check")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        wallet = econ.get_balance(interaction.guild.id, target.id)
        bank = econ.get_bank(interaction.guild.id, target.id)
        embed = discord.Embed(title=f"💰  {target.display_name}'s Balance", color=GOLD)
        embed.add_field(name="👛 Wallet", value=_fmt(wallet), inline=True)
        embed.add_field(name="🏦 Bank", value=_fmt(bank), inline=True)
        embed.add_field(name="💎 Net Worth", value=_fmt(wallet + bank), inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deposit", description="Move coins from your wallet to your bank (safe from /rob)")
    @app_commands.describe(amount="Amount to deposit, or 'all'")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
        amt = wallet if amount.lower() == "all" else _parse_amount(amount)
        if amt is None or amt <= 0:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Enter a positive number or `all`.", color=ERROR), ephemeral=True
            )
        if amt > wallet:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You only have {_fmt(wallet)} in your wallet.", color=ERROR), ephemeral=True
            )
        econ.add_balance(interaction.guild.id, interaction.user.id, -amt)
        new_bank = econ.add_bank(interaction.guild.id, interaction.user.id, amt)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"🏦 Deposited {_fmt(amt)}. Bank balance: {_fmt(new_bank)}", color=SUCCESS)
        )

    @app_commands.command(name="withdraw", description="Move coins from your bank back to your wallet")
    @app_commands.describe(amount="Amount to withdraw, or 'all'")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        bank = econ.get_bank(interaction.guild.id, interaction.user.id)
        amt = bank if amount.lower() == "all" else _parse_amount(amount)
        if amt is None or amt <= 0:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Enter a positive number or `all`.", color=ERROR), ephemeral=True
            )
        if amt > bank:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You only have {_fmt(bank)} in your bank.", color=ERROR), ephemeral=True
            )
        econ.add_bank(interaction.guild.id, interaction.user.id, -amt)
        new_wallet = econ.add_balance(interaction.guild.id, interaction.user.id, amt)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"👛 Withdrew {_fmt(amt)}. Wallet balance: {_fmt(new_wallet)}", color=SUCCESS)
        )

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
                embed=discord.Embed(description=f"❌ You don't have enough coins. Your wallet: {_fmt(bal)}", color=ERROR),
                ephemeral=True,
            )
        econ.add_balance(interaction.guild.id, interaction.user.id, -amount)
        econ.add_balance(interaction.guild.id, member.id, amount)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ {interaction.user.mention} sent {_fmt(amount)} to {member.mention}!", color=SUCCESS)
        )

    @app_commands.command(name="leaderboard", description="View the richest members in this server")
    async def leaderboard(self, interaction: discord.Interaction):
        top = econ.get_leaderboard(interaction.guild.id, 10)
        embed = discord.Embed(title="🏆  Coin Leaderboard", color=GOLD, description="Ranked by net worth (wallet + bank).")
        if not top:
            embed.description = "No one has earned any coins yet."
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, (uid, wallet, bank) in enumerate(top):
                member = interaction.guild.get_member(int(uid))
                name = member.mention if member else f"<@{uid}>"
                prefix = medals[i] if i < 3 else f"`#{i + 1}`"
                lines.append(f"{prefix}  {name} — {_fmt(wallet + bank)}")
            embed.description = "\n".join(lines)
        embed.set_footer(text="Yoran Studios  •  Economy")
        await interaction.response.send_message(embed=embed)

    # ── Earning ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="daily", description="Claim your daily reward")
    async def daily(self, interaction: discord.Interaction):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_daily", DAILY_COOLDOWN)
        if remaining > 0:
            h, m = divmod(int(remaining // 60), 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ You already claimed your daily reward. Try again in **{h}h {m}m**.", color=WARNING),
                ephemeral=True,
            )
        amount = random.randint(DAILY_MIN, DAILY_MAX)
        new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_daily", time.time())
        await interaction.response.send_message(embed=discord.Embed(
            title="🎁  Daily Reward Claimed!",
            description=f"You received {_fmt(amount)}!\nWallet balance: {_fmt(new_bal)}",
            color=SUCCESS,
        ))

    @app_commands.command(name="work", description="Work your job (or a odd job) to earn coins")
    async def work(self, interaction: discord.Interaction):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_work", WORK_COOLDOWN)
        if remaining > 0:
            m = int(remaining // 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ You're tired. Rest for **{m}m** before working again.", color=WARNING),
                ephemeral=True,
            )
        job = econ.get_job(interaction.guild.id, interaction.user.id)
        if job and job in JOBS:
            info = JOBS[job]
            amount = random.randint(info["min"], info["max"])
            flavor = f"As a **{job}**, you {info['flavor']}"
        else:
            amount = random.randint(WORK_MIN, WORK_MAX)
            flavor = random.choice(WORK_FLAVORS)
        new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_work", time.time())
        await interaction.response.send_message(embed=discord.Embed(
            title="🛠️  Work Complete",
            description=f"{flavor} and earned {_fmt(amount)}!\nWallet balance: {_fmt(new_bal)}",
            color=SUCCESS,
        ))

    @app_commands.command(name="crime", description="Attempt a risky crime for a bigger payout")
    async def crime(self, interaction: discord.Interaction):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_crime", CRIME_COOLDOWN)
        if remaining > 0:
            m = int(remaining // 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Lay low for **{m}m** before trying another crime.", color=WARNING),
                ephemeral=True,
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_crime", time.time())
        if random.random() < CRIME_SUCCESS_CHANCE:
            amount = random.randint(*CRIME_SUCCESS_RANGE)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
            desc = f"{random.choice(CRIME_SUCCESS_FLAVORS)} and made {_fmt(amount)}!\nWallet balance: {_fmt(new_bal)}"
            color = SUCCESS
        else:
            fine = random.randint(*CRIME_FAIL_RANGE)
            wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
            fine = min(fine, wallet)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, -fine)
            desc = f"{random.choice(CRIME_FAIL_FLAVORS)} and lost {_fmt(fine)}.\nWallet balance: {_fmt(new_bal)}"
            color = ERROR
        await interaction.response.send_message(embed=discord.Embed(title="🕵️  Crime", description=desc, color=color))

    @app_commands.command(name="beg", description="Beg for a few coins")
    async def beg(self, interaction: discord.Interaction):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_beg", BEG_COOLDOWN)
        if remaining > 0:
            m = int(remaining // 60) + 1
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Give it **{m}m** before begging again.", color=WARNING),
                ephemeral=True,
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_beg", time.time())
        if random.random() < BEG_NOTHING_CHANCE:
            desc = random.choice(BEG_NOTHING_FLAVORS)
            color = WARNING
        else:
            amount = random.randint(*BEG_RANGE)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
            desc = f"{random.choice(BEG_FLAVORS)} — you got {_fmt(amount)}!\nWallet balance: {_fmt(new_bal)}"
            color = SUCCESS
        await interaction.response.send_message(embed=discord.Embed(title="🥺  Begging", description=desc, color=color))

    @app_commands.command(name="rob", description="Attempt to rob coins from another member's wallet")
    @app_commands.describe(member="Member to rob")
    async def rob(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You can't rob yourself.", color=ERROR), ephemeral=True
            )
        if member.bot:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You can't rob a bot.", color=ERROR), ephemeral=True
            )
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_rob", ROB_COOLDOWN)
        if remaining > 0:
            m = int(remaining // 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Lay low for **{m}m** before robbing again.", color=WARNING),
                ephemeral=True,
            )
        target_wallet = econ.get_balance(interaction.guild.id, member.id)
        if target_wallet < ROB_MIN_TARGET_BALANCE:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ {member.mention} doesn't have enough coins in their wallet to be worth robbing.", color=ERROR),
                ephemeral=True,
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_rob", time.time())

        if random.random() < ROB_SUCCESS_CHANCE:
            pct = random.uniform(*ROB_STEAL_PCT)
            stolen = max(1, int(target_wallet * pct))
            econ.add_balance(interaction.guild.id, member.id, -stolen)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, stolen)
            desc = f"{random.choice(ROB_SUCCESS_FLAVORS).format(target=member.mention)} — you stole {_fmt(stolen)}!\nWallet balance: {_fmt(new_bal)}"
            color = SUCCESS
        else:
            wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
            fine = max(ROB_FINE_MIN, int(wallet * random.uniform(*ROB_FINE_PCT)))
            fine = min(fine, wallet)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, -fine)
            desc = f"{random.choice(ROB_FAIL_FLAVORS).format(target=member.mention)} — you paid a fine of {_fmt(fine)}.\nWallet balance: {_fmt(new_bal)}"
            color = ERROR

        await interaction.response.send_message(embed=discord.Embed(title="🦹  Robbery", description=desc, color=color))

    # ── Gambling ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="coinflip", description="Bet coins on a coin flip")
    @app_commands.describe(bet="Amount to bet", choice="Heads or tails")
    @app_commands.choices(choice=[app_commands.Choice(name="Heads", value="heads"), app_commands.Choice(name="Tails", value="tails")])
    async def coinflip(self, interaction: discord.Interaction, bet: app_commands.Range[int, 10, 1_000_000], choice: app_commands.Choice[str]):
        wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
        if bet > wallet:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You only have {_fmt(wallet)} in your wallet.", color=ERROR), ephemeral=True
            )
        result = random.choice(["heads", "tails"])
        won = result == choice.value
        econ.add_balance(interaction.guild.id, interaction.user.id, bet if won else -bet)
        new_bal = econ.get_balance(interaction.guild.id, interaction.user.id)
        emoji = "🪙"
        if won:
            desc = f"{emoji} Landed on **{result}** — you won {_fmt(bet)}!\nWallet balance: {_fmt(new_bal)}"
            color = SUCCESS
        else:
            desc = f"{emoji} Landed on **{result}** — you lost {_fmt(bet)}.\nWallet balance: {_fmt(new_bal)}"
            color = ERROR
        await interaction.response.send_message(embed=discord.Embed(title="🪙  Coinflip", description=desc, color=color))

    @app_commands.command(name="slots", description="Try your luck on the slot machine")
    @app_commands.describe(bet="Amount to bet")
    async def slots(self, interaction: discord.Interaction, bet: app_commands.Range[int, 10, 1_000_000]):
        wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
        if bet > wallet:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You only have {_fmt(wallet)} in your wallet.", color=ERROR), ephemeral=True
            )
        reels = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
        reel_display = " | ".join(reels)

        if reels[0] == reels[1] == reels[2]:
            multiplier = SLOT_TRIPLE_MULTIPLIER[reels[0]]
            winnings = bet * multiplier
            econ.add_balance(interaction.guild.id, interaction.user.id, winnings - bet)
            desc = f"[ {reel_display} ]\n🎉 Jackpot! Three of a kind pays **{multiplier}x** — you won {_fmt(winnings - bet)}!"
            color = SUCCESS
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            desc = f"[ {reel_display} ]\nA pair! You broke even, bet {_fmt(bet)} returned."
            color = WARNING
        else:
            econ.add_balance(interaction.guild.id, interaction.user.id, -bet)
            desc = f"[ {reel_display} ]\nNo match — you lost {_fmt(bet)}."
            color = ERROR

        new_bal = econ.get_balance(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(title="🎰  Slots", description=desc, color=color)
        embed.set_footer(text=f"Wallet balance: {new_bal:,} {econ.CURRENCY_NAME}")
        await interaction.response.send_message(embed=embed)

    # ── Jobs ─────────────────────────────────────────────────────────────────────

    @app_commands.command(name="jobs", description="View available jobs and their pay ranges")
    async def jobs_list(self, interaction: discord.Interaction):
        job = econ.get_job(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(
            title="💼  Available Jobs",
            description=f"Your current job: **{job or 'Unemployed'}**\nUse `/setjob` to apply.",
            color=INFO,
        )
        for name, info in JOBS.items():
            embed.add_field(name=name, value=f"{econ.CURRENCY_EMOJI} {info['min']}-{info['max']} per `/work`", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setjob", description="Apply for a job (changes your /work payout)")
    @app_commands.describe(job="Job to apply for")
    @app_commands.choices(job=[app_commands.Choice(name=name, value=name) for name in JOBS] + [app_commands.Choice(name="Unemployed", value="Unemployed")])
    async def setjob(self, interaction: discord.Interaction, job: app_commands.Choice[str]):
        chosen = None if job.value == "Unemployed" else job.value
        econ.set_job(interaction.guild.id, interaction.user.id, chosen)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ You are now a **{chosen or 'Unemployed'}**.", color=SUCCESS)
        )

    # ── Shop ─────────────────────────────────────────────────────────────────────

    @app_commands.command(name="shop", description="View items available in the coin shop")
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
            embed.set_footer(text="Use /buy <item> to purchase")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy an item from the coin shop")
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

    @app_commands.command(name="shop-add", description="Add an item to the coin shop (admin)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(name="Item name", price="Price in coins", role="Role granted when purchased")
    @is_admin()
    async def shop_additem(self, interaction: discord.Interaction, name: str, price: app_commands.Range[int, 1, 1_000_000], role: discord.Role):
        econ.add_shop_item(interaction.guild.id, name, price, role.id)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Added **{name}** ({_fmt(price)}) → {role.mention} to the shop.", color=SUCCESS)
        )

    @app_commands.command(name="shop-remove", description="Remove an item from the coin shop (admin)")
    @app_commands.default_permissions(administrator=True)
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


def _parse_amount(amount: str) -> int | None:
    try:
        value = int(amount)
        return value if value > 0 else None
    except ValueError:
        return None


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
