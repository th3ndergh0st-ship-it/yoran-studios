import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR
from utils import is_admin
from cogs.verification import VerificationView, MEMBER_ROLE_NAME, UNVERIFIED_ROLE_NAME
from cogs.tickets import TicketOpenView, _load as _load_tickets, _save as _save_tickets
from cogs.welcome import _load as _load_welcome, _save as _save_welcome


# ── Welcome / Goodbye config modals ────────────────────────────────────────────

class WelcomeConfigModal(discord.ui.Modal, title="👋 Configure Welcome Message"):
    msg_title = discord.ui.TextInput(label="Title", placeholder="Welcome to Yoran Studios!", max_length=100, required=False)
    message   = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        placeholder="Use {user}, {server}, {count} as placeholders",
        default="Welcome {user} to {server}! You're member #{count}.",
        max_length=1000,
    )
    color_hex = discord.ui.TextInput(label="Color hex (optional)", placeholder="e.g. 7B2FBE", max_length=6, required=False)
    banner    = discord.ui.TextInput(label="Banner image URL (optional)", max_length=500, required=False)
    ping      = discord.ui.TextInput(label="Ping the member? (yes/no)", default="yes", max_length=3, required=False)

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int(self.color_hex.value, 16) if self.color_hex.value else PRIMARY
        except ValueError:
            color = PRIMARY
        data = _load_welcome()
        data.setdefault(str(interaction.guild.id), {})["welcome"] = {
            "channel_id": self.channel.id,
            "title": self.msg_title.value or "Welcome!",
            "message": self.message.value,
            "color": color,
            "banner": self.banner.value or None,
            "ping": self.ping.value.strip().lower() != "no",
        }
        _save_welcome(data)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Welcome messages will now be sent to {self.channel.mention}.", color=SUCCESS),
            ephemeral=True,
        )


class GoodbyeConfigModal(discord.ui.Modal, title="👋 Configure Goodbye Message"):
    msg_title = discord.ui.TextInput(label="Title", placeholder="Goodbye!", max_length=100, required=False)
    message   = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        placeholder="Use {user}, {server}, {count} as placeholders",
        default="**{user}** has left {server}. We're now at {count} members.",
        max_length=1000,
    )
    color_hex = discord.ui.TextInput(label="Color hex (optional)", placeholder="e.g. E74C3C", max_length=6, required=False)

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int(self.color_hex.value, 16) if self.color_hex.value else ERROR
        except ValueError:
            color = ERROR
        data = _load_welcome()
        data.setdefault(str(interaction.guild.id), {})["goodbye"] = {
            "channel_id": self.channel.id,
            "title": self.msg_title.value or "Goodbye!",
            "message": self.message.value,
            "color": color,
        }
        _save_welcome(data)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Goodbye messages will now be sent to {self.channel.mention}.", color=SUCCESS),
            ephemeral=True,
        )


# ── Cog ───────────────────────────────────────────────────────────────────────

class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have the required role for this command.", color=ERROR),
                ephemeral=True,
            )

    @app_commands.command(name="setup-verification", description="Post the verification panel (auto-creates Member/Unverified roles)")
    @app_commands.describe(channel="Channel to post the verification panel in")
    @is_admin()
    async def setup_verification(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        created = []
        member_role = discord.utils.get(guild.roles, name=MEMBER_ROLE_NAME)
        if member_role is None:
            member_role = await guild.create_role(
                name=MEMBER_ROLE_NAME,
                colour=discord.Colour.from_rgb(149, 165, 166),
                permissions=discord.Permissions.none(),
                reason="Verification setup: verified-member role",
            )
            created.append(member_role)
        unverified_role = discord.utils.get(guild.roles, name=UNVERIFIED_ROLE_NAME)
        if unverified_role is None:
            unverified_role = await guild.create_role(
                name=UNVERIFIED_ROLE_NAME,
                colour=discord.Colour.from_rgb(100, 100, 100),
                permissions=discord.Permissions.none(),
                reason="Verification setup: pre-verification role",
            )
            created.append(unverified_role)

        embed = discord.Embed(
            title="🎟️  Member Verification",
            description=(
                f"Welcome to **{guild.name}**!\n\n"
                "> **1.** Read the server rules\n"
                "> **2.** Press the **Verify** button below\n"
                "> **3.** Instantly unlock the rest of the server\n\n"
                "Having trouble verifying? Open a support ticket and our staff will help you out."
            ),
            color=PRIMARY,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text=f"{guild.name}  •  Verification", icon_url=guild.icon.url if guild.icon else None)
        await channel.send(embed=embed, view=VerificationView())

        summary = f"✅ Verification panel posted in {channel.mention}."
        if created:
            summary += "\nCreated roles: " + ", ".join(r.mention for r in created)
        else:
            summary += f"\nUsing existing **{MEMBER_ROLE_NAME}** and **{UNVERIFIED_ROLE_NAME}** roles."
        summary += "\n⚠️ Make sure my bot role sits **above** both roles so I can assign them."
        await interaction.followup.send(embed=discord.Embed(description=summary, color=SUCCESS), ephemeral=True)

    @app_commands.command(name="setup-tickets", description="Post the support ticket panel in a channel")
    @app_commands.describe(
        channel="Channel to post the ticket panel in",
        category="Category new ticket channels should be created under",
        logs_channel="Channel where ticket open/close logs will be sent (e.g. #ticket-logs)",
    )
    @is_admin()
    async def setup_tickets(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel = None,
        logs_channel: discord.TextChannel = None,
    ):
        data = _load_tickets()
        gid = str(interaction.guild.id)
        data.setdefault(gid, {})
        if category:
            data[gid]["category_id"] = category.id
        if logs_channel:
            data[gid]["logs_channel_id"] = logs_channel.id
        _save_tickets(data)

        embed = discord.Embed(
            title=f"🎫  {interaction.guild.name} — Support Center",
            description=(
                "Need a hand? Open a private ticket and our team will assist you.\n\n"
                "> 🐛  **Bug Reports** — issues found in our games\n"
                "> 💬  **General Support** — questions and account help\n"
                "> 💡  **Feedback** — ideas and suggestions for our games\n"
                "> 🤝  **Partnerships** — collabs and business inquiries\n\n"
                "Press the button below — a private channel visible only to you and staff will be created."
            ),
            color=PRIMARY,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text=f"{interaction.guild.name}  •  Support", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        await channel.send(embed=embed, view=TicketOpenView())
        summary = f"✅ Ticket panel posted in {channel.mention}."
        if category:
            summary += f"\nTickets will be created under **{category.name}**."
        if logs_channel:
            summary += f"\nOpen/close logs will go to {logs_channel.mention}."
        await interaction.response.send_message(
            embed=discord.Embed(description=summary, color=SUCCESS),
            ephemeral=True,
        )

    @app_commands.command(name="setup-welcome", description="Configure the welcome message for new members")
    @app_commands.describe(channel="Channel where welcome messages will be sent")
    @is_admin()
    async def setup_welcome(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.send_modal(WelcomeConfigModal(channel))

    @app_commands.command(name="setup-goodbye", description="Configure the goodbye message for departing members")
    @app_commands.describe(channel="Channel where goodbye messages will be sent")
    @is_admin()
    async def setup_goodbye(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.send_modal(GoodbyeConfigModal(channel))


async def setup(bot: commands.Bot):
    await bot.add_cog(Setup(bot))
