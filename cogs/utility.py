import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR, WARNING, INFO
from utils import is_helper, is_support


class SuggestModal(discord.ui.Modal, title="💡 Submit a Suggestion"):
    sug_title   = discord.ui.TextInput(label="Title", placeholder="Brief title for your suggestion", max_length=100)
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        placeholder="Describe your suggestion in detail...",
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        channel = discord.utils.get(interaction.guild.text_channels, name="suggestions")
        if not channel:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ No `#suggestions` channel found. Ask an admin to create one.", color=ERROR),
                ephemeral=True,
            )
        embed = discord.Embed(title=f"💡  {self.sug_title.value}", description=self.description.value, color=INFO)
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Status", value="🟡 Pending", inline=True)
        embed.set_footer(text=f"User ID: {interaction.user.id}")
        embed.timestamp = discord.utils.utcnow()
        msg = await channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Suggestion submitted to {channel.mention}!", color=SUCCESS),
            ephemeral=True,
        )


class ReportModal(discord.ui.Modal, title="🚨 Report a User"):
    description = discord.ui.TextInput(
        label="What happened?",
        style=discord.TextStyle.paragraph,
        placeholder="Describe the situation in detail. Include any relevant context...",
        max_length=1000,
    )
    evidence = discord.ui.TextInput(
        label="Evidence links (optional)",
        placeholder="Links to screenshots or messages",
        max_length=500,
        required=False,
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        channel = (
            discord.utils.get(interaction.guild.text_channels, name="staff-reports")
            or discord.utils.get(interaction.guild.text_channels, name="mod-reports")
            or discord.utils.get(interaction.guild.text_channels, name="reports")
        )
        if not channel:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ No staff reports channel found. Contact a staff member directly.", color=ERROR),
                ephemeral=True,
            )
        embed = discord.Embed(title="🚨  User Report", color=ERROR)
        embed.set_thumbnail(url=self.member.display_avatar.url)
        embed.add_field(name="👤  Reported User", value=f"{self.member.mention}\n`{self.member.id}`", inline=True)
        embed.add_field(name="📢  Reported By", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
        embed.add_field(name="📋  Description", value=self.description.value, inline=False)
        if self.evidence.value:
            embed.add_field(name="🖼️  Evidence", value=self.evidence.value, inline=False)
        embed.set_footer(text=f"Reported in #{interaction.channel.name}")
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)
        await interaction.response.send_message(
            embed=discord.Embed(description="✅ Report submitted to staff. Thank you!", color=SUCCESS),
            ephemeral=True,
        )


class PollModal(discord.ui.Modal, title="📊 Create a Poll"):
    question = discord.ui.TextInput(label="Question", placeholder="What do you want to ask?", max_length=200)
    options  = discord.ui.TextInput(
        label="Options (one per line, max 5)",
        style=discord.TextStyle.paragraph,
        placeholder="Option A\nOption B\nOption C",
        max_length=500,
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        lines = [l.strip() for l in self.options.value.split("\n") if l.strip()][:5]
        if len(lines) < 2:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Provide at least 2 options (one per line).", color=ERROR),
                ephemeral=True,
            )
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        options_text = "\n".join(f"{emojis[i]}  {opt}" for i, opt in enumerate(lines))
        embed = discord.Embed(title=f"📊  {self.question.value}", description=options_text, color=INFO)
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="Vote by reacting below!")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Poll created in {self.channel.mention}!", color=SUCCESS),
            ephemeral=True,
        )
        msg = await self.channel.send(embed=embed)
        for i in range(len(lines)):
            await msg.add_reaction(emojis[i])


class Utility(commands.Cog):
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


    @app_commands.command(name="kingofyapping", description="Reveals the server's undisputed King of Yapping 👑")
    async def kingofyapping(self, interaction: discord.Interaction):
        from cogs.levels import get_guild_stats
        stats = get_guild_stats(interaction.guild.id)
        ranked = sorted(
            ((uid, u) for uid, u in stats.items() if u.get("messages", 0) > 0),
            key=lambda kv: kv[1].get("messages", 0),
            reverse=True,
        )
        if not ranked:
            return await interaction.response.send_message(
                embed=discord.Embed(description="🤫 Suspiciously quiet in here... no yappers detected yet.", color=PRIMARY)
            )

        uid, top = ranked[0]
        king = interaction.guild.get_member(int(uid))
        king_name = king.mention if king else f"<@{uid}>"
        count = top.get("messages", 0)

        embed = discord.Embed(
            title="👑  The King of Yapping",
            description=(
                f"All rise for {king_name}! 🗣️\n\n"
                f"With a staggering **{count:,} messages**, nobody in **{interaction.guild.name}** "
                "talks more. Certified yapper. Keyboard warriors fear them. Silence has never met them."
            ),
            color=0xF1C40F,
        )
        if king:
            embed.set_thumbnail(url=king.display_avatar.url)
        if len(ranked) > 1:
            r_uid, r = ranked[1]
            runner = interaction.guild.get_member(int(r_uid))
            embed.add_field(
                name="👀 Closest challenger",
                value=f"{runner.mention if runner else f'<@{r_uid}>'} — `{r.get('messages', 0):,}` messages... catching up?",
                inline=False,
            )
        embed.set_footer(text="Yoran Studios  •  All in good fun 💜")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="Check the bot's latency")
    async def ping(self, interaction: discord.Interaction):
        ws = round(self.bot.latency * 1000)
        if ws < 80:
            label, dot, color = "Excellent", "🟢", SUCCESS
        elif ws < 180:
            label, dot, color = "Good", "🟡", WARNING
        else:
            label, dot, color = "High Latency", "🔴", ERROR
        embed = discord.Embed(title="🏓  Pong!", color=color)
        embed.add_field(name="📡  WebSocket", value=f"`{ws} ms`", inline=True)
        embed.add_field(name="📊  Status", value=f"{dot} {label}", inline=True)
        embed.set_footer(text="Yoran", icon_url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="View information about Yoran")
    async def botinfo(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🤖  Yoran", color=PRIMARY)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="🏢  Studio", value="Yoran Studios", inline=True)
        embed.add_field(name="📚  Library", value="`discord.py 2.x`", inline=True)
        embed.add_field(name="🌐  Servers", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="📡  Latency", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        embed.add_field(name="🎯  Purpose", value="Multi-Game Roblox Community", inline=True)
        embed.set_footer(text="Yoran", icon_url=self.bot.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="userinfo", description="View info about a member")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member="Member to look up")
    @is_helper()
    async def info_user(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        roles = [r.mention for r in reversed(target.roles[1:])]
        embed = discord.Embed(color=target.color if str(target.color) != "#000000" else PRIMARY)
        embed.set_author(name=str(target), icon_url=target.display_avatar.url)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🏷️  Username", value=str(target), inline=True)
        embed.add_field(name="🆔  ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="🤖  Bot", value="Yes" if target.bot else "No", inline=True)
        embed.add_field(name="📅  Account Created", value=discord.utils.format_dt(target.created_at, "R"), inline=True)
        embed.add_field(name="📥  Joined Server", value=discord.utils.format_dt(target.joined_at, "R"), inline=True)
        embed.add_field(name="⭐  Top Role", value=target.top_role.mention, inline=True)
        embed.add_field(name=f"🎭  Roles ({len(roles)})", value=" ".join(roles)[:1024] if roles else "None", inline=False)
        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="View info about this server")
    @app_commands.default_permissions(manage_messages=True)
    @is_helper()
    async def info_server(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=f"🏠  {guild.name}", color=PRIMARY)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        embed.add_field(name="👑  Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="👥  Members", value=f"`{guild.member_count}`", inline=True)
        embed.add_field(name="🎭  Roles", value=f"`{len(guild.roles)}`", inline=True)
        embed.add_field(name="💬  Text Channels", value=f"`{len(guild.text_channels)}`", inline=True)
        embed.add_field(name="🔊  Voice Channels", value=f"`{len(guild.voice_channels)}`", inline=True)
        embed.add_field(name="✨  Boost Level", value=f"`Tier {guild.premium_tier}` ({guild.premium_subscription_count} boosts)", inline=True)
        embed.add_field(name="📅  Created", value=discord.utils.format_dt(guild.created_at, "R"), inline=False)
        embed.set_footer(text=f"ID: {guild.id}", icon_url=self.bot.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="View a member's avatar")
    @app_commands.describe(member="Member to get the avatar of")
    async def info_avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        embed = discord.Embed(title=f"🖼️  {target.display_name}'s Avatar", color=PRIMARY)
        embed.set_image(url=target.display_avatar.url)
        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Download", url=str(target.display_avatar.url), style=discord.ButtonStyle.link, emoji="⬇️"))
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="membercount", description="View the server's member count")
    async def info_membercount(self, interaction: discord.Interaction):
        guild = interaction.guild
        bots   = sum(1 for m in guild.members if m.bot)
        humans = guild.member_count - bots
        embed = discord.Embed(title=f"👥  {guild.name} — Members", color=PRIMARY)
        embed.add_field(name="👤  Humans", value=f"`{humans}`", inline=True)
        embed.add_field(name="🤖  Bots", value=f"`{bots}`", inline=True)
        embed.add_field(name="📊  Total", value=f"`{guild.member_count}`", inline=True)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text=guild.name, icon_url=guild.icon.url if guild.icon else None)
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roleinfo", description="View info about a role")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(role="Role to look up")
    @is_helper()
    async def info_role(self, interaction: discord.Interaction, role: discord.Role):
        perms = [p.replace("_", " ").title() for p, v in role.permissions if v]
        embed = discord.Embed(title=f"🎭  {role.name}", color=role.color if role.color.value else PRIMARY)
        embed.add_field(name="🆔  ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="👥  Members", value=f"`{len(role.members)}`", inline=True)
        embed.add_field(name="📌  Position", value=f"`{role.position}`", inline=True)
        embed.add_field(name="🎨  Color", value=f"`{str(role.color)}`", inline=True)
        embed.add_field(name="🔔  Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="🖥️  Hoisted", value="Yes" if role.hoist else "No", inline=True)
        if perms:
            embed.add_field(
                name=f"🔑  Key Permissions",
                value=", ".join(perms[:10]) + ("…" if len(perms) > 10 else ""),
                inline=False,
            )
        embed.set_footer(text=f"Created {discord.utils.format_dt(role.created_at, 'R')}")
        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="suggest", description="Submit a suggestion for the server")
    async def community_suggest(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SuggestModal())

    @app_commands.command(name="report", description="Report a user to staff")
    @app_commands.describe(member="Member you want to report")
    async def community_report(self, interaction: discord.Interaction, member: discord.Member):
        if member == interaction.user:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot report yourself.", color=ERROR),
                ephemeral=True,
            )
        await interaction.response.send_modal(ReportModal(member))

    @app_commands.command(name="poll", description="Create a poll in a channel")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(channel="Channel to post the poll in")
    @is_support()
    async def community_poll(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.send_modal(PollModal(channel))


    @app_commands.command(name="help", description="View all available commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖  Yoran — Commands",
            description="All commands use `/`. Some open a form — just fill it in and submit!",
            color=PRIMARY,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(
            name="🎮  Games",
            value="`/games` `/gameinfo` `/notify`",
            inline=False,
        )
        embed.add_field(
            name="🪙  Economy",
            value="`/balance` `/daily` `/work` `/crime` `/beg` `/rob`\n"
                  "`/pay` `/deposit` `/withdraw` `/leaderboard`\n"
                  "`/coinflip` `/slots` `/jobs` `/setjob`\n"
                  "`/shop` `/buy`",
            inline=False,
        )
        embed.add_field(
            name="📊  Levels",
            value="`/rank` `/levels` — earn XP by chatting, unlock Level roles!",
            inline=False,
        )
        embed.add_field(
            name="🧠  Learn",
            value="`/tip` `/trivia`",
            inline=False,
        )
        embed.add_field(
            name="💬  Community",
            value="`/suggest` `/report` `/avatar` `/membercount` `/invites` `/verifysub` `/kingofyapping`",
            inline=False,
        )
        embed.add_field(
            name="⚙️  Utility",
            value="`/ping` `/botinfo` `/help`",
            inline=False,
        )
        embed.add_field(
            name="🛡️  Staff",
            value="*Staff commands (`/ban`, `/softban`, `/kick`, `/warn`, `/cases`, `/purge`, `/announce`, "
                  "`/poll`, `/giveaway`, `/gamepanel`, `/shop-add`…) only appear in the `/` menu "
                  "if your role has the matching permissions.*",
            inline=False,
        )
        embed.set_footer(text="Yoran  •  Yoran Studios", icon_url=self.bot.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
