import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import SUCCESS, ERROR, WARNING, GOLD, PRIMARY, INFO
from utils import is_admin
import economy_data as econ
import settings

DEV_ROLE_ID = 1523445699377627186


def is_dev():
    async def predicate(interaction: discord.Interaction) -> bool:
        if any(r.id == DEV_ROLE_ID for r in interaction.user.roles):
            return True
        raise app_commands.CheckFailure("dev_role")
    return app_commands.check(predicate)

def S(key):
    return settings.get("economy", key)


SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "💎", "7️⃣"]
SLOT_WEIGHTS = [35, 30, 20, 10, 5]
SLOT_TRIPLE_MULTIPLIER = {"🍒": 3, "🍋": 3, "🍊": 4, "💎": 6, "7️⃣": 10}

JOBS = {
    "Playtester":         {"min": 30, "max": 80,  "flavor": "found bugs in the newest build"},
    "Scripter":            {"min": 45, "max": 110, "flavor": "shipped a new Lua script"},
    "3D Artist":           {"min": 40, "max": 100, "flavor": "modeled a prop for the next game"},
    "Community Manager":   {"min": 35, "max": 90,  "flavor": "kept the community drama-free"},
    "Marketer":            {"min": 30, "max": 85,  "flavor": "posted a trailer that went semi-viral"},
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


    @app_commands.command(name="addmoney", description="Add coins to a member's wallet (dev only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Member to give coins to", amount="Amount to add")
    @is_dev()
    async def addmoney(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 100_000_000]):
        new_bal = econ.add_balance(interaction.guild.id, member.id, amount)
        embed = discord.Embed(
            title="💵  Coins Added",
            description=f"Added {_fmt(amount)} to {member.mention}.\nNew wallet balance: {_fmt(new_bal)}",
            color=SUCCESS,
        )
        embed.set_footer(text=f"By {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removemoney", description="Remove coins from a member's wallet + bank (dev only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Member to take coins from", amount="Amount to remove, or 'all'")
    @is_dev()
    async def removemoney(self, interaction: discord.Interaction, member: discord.Member, amount: str):
        wallet = econ.get_balance(interaction.guild.id, member.id)
        bank = econ.get_bank(interaction.guild.id, member.id)
        total = wallet + bank

        amt = total if amount.lower() == "all" else _parse_amount(amount)
        if amt is None or amt <= 0:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Enter a positive number or `all`.", color=ERROR), ephemeral=True
            )
        amt = min(amt, total)

        from_wallet = min(amt, wallet)
        from_bank = amt - from_wallet
        if from_wallet:
            econ.add_balance(interaction.guild.id, member.id, -from_wallet)
        if from_bank:
            econ.add_bank(interaction.guild.id, member.id, -from_bank)

        new_wallet = econ.get_balance(interaction.guild.id, member.id)
        new_bank = econ.get_bank(interaction.guild.id, member.id)
        embed = discord.Embed(
            title="💸  Coins Removed",
            description=(
                f"Removed {_fmt(amt)} from {member.mention} "
                f"(👛 {from_wallet:,} wallet + 🏦 {from_bank:,} bank).\n"
                f"New balance — 👛 {_fmt(new_wallet)} · 🏦 {_fmt(new_bank)}"
            ),
            color=WARNING,
        )
        embed.set_footer(text=f"By {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    leaderboard = app_commands.Group(name="leaderboard", description="Server leaderboards")

    def _lb_embed(self, interaction: discord.Interaction, title: str, footer: str, lines: list[str]) -> discord.Embed:
        embed = discord.Embed(title=title, color=GOLD)
        embed.description = "\n".join(lines) if lines else "Nothing to rank yet — get active!"
        embed.set_footer(text=f"Yoran Studios  •  {footer}")
        return embed

    @staticmethod
    def _lb_prefix(i: int) -> str:
        medals = ["🥇", "🥈", "🥉"]
        return medals[i] if i < 3 else f"`#{i + 1}`"

    @staticmethod
    def _lb_name(interaction: discord.Interaction, uid: str) -> str:
        member = interaction.guild.get_member(int(uid))
        return member.mention if member else f"<@{uid}>"

    @leaderboard.command(name="coins", description="Top members by net worth (wallet + bank)")
    async def leaderboard_coins(self, interaction: discord.Interaction):
        lines = [
            f"{self._lb_prefix(i)}  {self._lb_name(interaction, uid)} — {_fmt(wallet + bank)}"
            for i, (uid, wallet, bank) in enumerate(econ.get_leaderboard(interaction.guild.id, 10))
        ]
        await interaction.response.send_message(
            embed=self._lb_embed(interaction, "🏆  Coin Leaderboard", "Ranked by net worth (wallet + bank)", lines)
        )

    @leaderboard.command(name="levels", description="Top members by level and XP")
    async def leaderboard_levels(self, interaction: discord.Interaction):
        from cogs.levels import get_guild_stats
        stats = get_guild_stats(interaction.guild.id)
        ranked = sorted(stats.items(), key=lambda kv: (kv[1].get("level", 0), kv[1].get("xp", 0)), reverse=True)[:10]
        lines = [
            f"{self._lb_prefix(i)}  {self._lb_name(interaction, uid)} — Level **{u.get('level', 0)}** (`{u.get('xp', 0):,}` xp)"
            for i, (uid, u) in enumerate(ranked)
        ]
        await interaction.response.send_message(
            embed=self._lb_embed(interaction, "🏆  Level Leaderboard", "Ranked by level and XP", lines)
        )

    lb_messages = app_commands.Group(name="messages", description="Message leaderboards", parent=leaderboard)

    async def _send_message_board(self, interaction: discord.Interaction, field: str, key_field: str | None,
                                  current_key: str | None, title: str, footer: str):
        from cogs.levels import get_guild_stats
        stats = get_guild_stats(interaction.guild.id)

        def value_of(u: dict) -> int:
            if key_field and u.get(key_field) != current_key:
                return 0
            return u.get(field, 0)

        ranked = sorted(stats.items(), key=lambda kv: value_of(kv[1]), reverse=True)
        ranked = [(uid, u) for uid, u in ranked if value_of(u) > 0][:10]
        lines = [
            f"{self._lb_prefix(i)}  {self._lb_name(interaction, uid)} — `{value_of(u):,}` messages"
            for i, (uid, u) in enumerate(ranked)
        ]
        await interaction.response.send_message(embed=self._lb_embed(interaction, title, footer, lines))

    @lb_messages.command(name="alltime", description="Top members by messages sent (all time)")
    async def leaderboard_messages_alltime(self, interaction: discord.Interaction):
        await self._send_message_board(interaction, "messages", None, None,
                                       "🏆  Message Leaderboard — All Time", "Ranked by total messages sent")

    @lb_messages.command(name="weekly", description="Top members by messages sent this week")
    async def leaderboard_messages_weekly(self, interaction: discord.Interaction):
        from cogs.levels import current_week_key
        await self._send_message_board(interaction, "messages_week", "week_key", current_week_key(),
                                       "🏆  Message Leaderboard — This Week", "Resets every Monday (UTC)")

    @lb_messages.command(name="daily", description="Top members by messages sent today")
    async def leaderboard_messages_daily(self, interaction: discord.Interaction):
        from cogs.levels import current_day_key
        await self._send_message_board(interaction, "messages_day", "day_key", current_day_key(),
                                       "🏆  Message Leaderboard — Today", "Resets daily at midnight UTC")

    @leaderboard.command(name="invites", description="Top members by invites")
    async def leaderboard_invites(self, interaction: discord.Interaction):
        from cogs.invites import get_invite_counts
        counts = get_invite_counts(interaction.guild.id)
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
        lines = [
            f"{self._lb_prefix(i)}  {self._lb_name(interaction, uid)} — `{c:,}` invites"
            for i, (uid, c) in enumerate(ranked)
        ]
        await interaction.response.send_message(
            embed=self._lb_embed(interaction, "🏆  Invite Leaderboard", "Ranked by members invited", lines)
        )


    @app_commands.command(name="daily", description="Claim your daily reward")
    async def daily(self, interaction: discord.Interaction):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_daily", S("daily_cooldown"))
        if remaining > 0:
            h, m = divmod(int(remaining // 60), 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ You already claimed your daily reward. Try again in **{h}h {m}m**.", color=WARNING),
                ephemeral=True,
            )
        amount = random.randint(S("daily_min"), S("daily_max"))
        new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_daily", time.time())
        await interaction.response.send_message(embed=discord.Embed(
            title="🎁  Daily Reward Claimed!",
            description=f"You received {_fmt(amount)}!\nWallet balance: {_fmt(new_bal)}",
            color=SUCCESS,
        ))

    @app_commands.command(name="work", description="Work your job (or a odd job) to earn coins")
    async def work(self, interaction: discord.Interaction):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_work", S("work_cooldown"))
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
            amount = random.randint(S("work_min"), S("work_max"))
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
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_crime", S("crime_cooldown"))
        if remaining > 0:
            m = int(remaining // 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Lay low for **{m}m** before trying another crime.", color=WARNING),
                ephemeral=True,
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_crime", time.time())
        if random.random() < S("crime_success_chance"):
            amount = random.randint(S("crime_win_min"), S("crime_win_max"))
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, amount)
            desc = f"{random.choice(CRIME_SUCCESS_FLAVORS)} and made {_fmt(amount)}!\nWallet balance: {_fmt(new_bal)}"
            color = SUCCESS
        else:
            fine = random.randint(S("crime_fail_min"), S("crime_fail_max"))
            wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
            fine = min(fine, wallet)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, -fine)
            desc = f"{random.choice(CRIME_FAIL_FLAVORS)} and lost {_fmt(fine)}.\nWallet balance: {_fmt(new_bal)}"
            color = ERROR
        await interaction.response.send_message(embed=discord.Embed(title="🕵️  Crime", description=desc, color=color))

    @app_commands.command(name="beg", description="Beg for a few coins")
    async def beg(self, interaction: discord.Interaction):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_beg", S("beg_cooldown"))
        if remaining > 0:
            m = int(remaining // 60) + 1
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Give it **{m}m** before begging again.", color=WARNING),
                ephemeral=True,
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_beg", time.time())
        if random.random() < S("beg_nothing_chance"):
            desc = random.choice(BEG_NOTHING_FLAVORS)
            color = WARNING
        else:
            amount = random.randint(S("beg_min"), S("beg_max"))
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
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_rob", S("rob_cooldown"))
        if remaining > 0:
            m = int(remaining // 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Lay low for **{m}m** before robbing again.", color=WARNING),
                ephemeral=True,
            )
        target_wallet = econ.get_balance(interaction.guild.id, member.id)
        if target_wallet < S("rob_min_target_balance"):
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ {member.mention} doesn't have enough coins in their wallet to be worth robbing.", color=ERROR),
                ephemeral=True,
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_rob", time.time())

        if random.random() < S("rob_success_chance"):
            pct = random.uniform(S("rob_steal_pct_min"), S("rob_steal_pct_max"))
            stolen = max(1, int(target_wallet * pct))
            econ.add_balance(interaction.guild.id, member.id, -stolen)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, stolen)
            desc = f"{random.choice(ROB_SUCCESS_FLAVORS).format(target=member.mention)} — you stole {_fmt(stolen)}!\nWallet balance: {_fmt(new_bal)}"
            color = SUCCESS
        else:
            wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
            fine = max(S("rob_fine_min"), int(wallet * random.uniform(S("rob_fine_pct_min"), S("rob_fine_pct_max"))))
            fine = min(fine, wallet)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, -fine)
            desc = f"{random.choice(ROB_FAIL_FLAVORS).format(target=member.mention)} — you paid a fine of {_fmt(fine)}.\nWallet balance: {_fmt(new_bal)}"
            color = ERROR

        await interaction.response.send_message(embed=discord.Embed(title="🦹  Robbery", description=desc, color=color))


    @app_commands.command(name="coinflip", description="Bet coins on a coin flip")
    @app_commands.describe(bet="Amount to bet", choice="Heads or tails")
    @app_commands.choices(choice=[app_commands.Choice(name="Heads", value="heads"), app_commands.Choice(name="Tails", value="tails")])
    async def coinflip(self, interaction: discord.Interaction, bet: app_commands.Range[int, 10, 1_000_000], choice: app_commands.Choice[str]):
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_gamble", S("gamble_cooldown"))
        if remaining > 0:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Easy, gambler — wait **{int(remaining) + 1}s** before betting again.", color=WARNING),
                ephemeral=True,
            )
        wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
        if bet > wallet:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You only have {_fmt(wallet)} in your wallet.", color=ERROR), ephemeral=True
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_gamble", time.time())
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
        remaining = _cooldown_remaining(interaction.guild.id, interaction.user.id, "last_gamble", S("gamble_cooldown"))
        if remaining > 0:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ Easy, gambler — wait **{int(remaining) + 1}s** before betting again.", color=WARNING),
                ephemeral=True,
            )
        wallet = econ.get_balance(interaction.guild.id, interaction.user.id)
        if bet > wallet:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ You only have {_fmt(wallet)} in your wallet.", color=ERROR), ephemeral=True
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_gamble", time.time())
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
