import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR, WARNING
from utils import is_owner, is_admin, HELPER_ROLES
from cogs.verification import VerificationView
from cogs.tickets import TicketOpenView, _load as _load_tickets, _save as _save_tickets
from cogs.welcome import _load as _load_welcome, _save as _save_welcome

# ── Rank hierarchy (highest → lowest) ──────────────────────────────────────────
#
#  👑 Owner              full control, server founder(s)
#  💼 Co-Owner           full control, trusted second-in-command
#  ⚙️ Developer          full control, builds the games & the bot
#  🛡️ Head Administrator administration + escalation point for admins
#  🛡️ Administrator      day-to-day server administration
#  🔨 Head Moderator     senior moderation, can ban
#  🔨 Moderator          standard moderation (no ban)
#  🔰 Trial Moderator    moderation-in-training (no kick/ban)
#  🎟️ Support Team       tickets & member support
#  🤝 Helper             community helpers, read-only mod tools
#  🎬 Content Creator    badge — community content creators
#  🤝 Partner            badge — partnered communities/creators
#  🧪 Beta Tester        badge — early access to unreleased games
#  💎 Server Booster     badge — server boosters
#  ✅ Member             verified regular member
#  🔒 Unverified         pre-verification, minimal access
#
# The first 10 ranks map to utils.py's OWNER/ADMIN/MOD/SUPPORT/HELPER tiers,
# which is what every @is_xxx() command check in the bot enforces. The next
# 4 are cosmetic badges meant to be worn *on top of* ✅ Member — they grant
# no extra command access, only recognition + the color/hoist.

ROLES = [
    {"name": "👑 Owner",              "color": discord.Color.from_rgb(255, 215, 0),   "hoist": True,  "mentionable": False, "permissions": discord.Permissions.all()},
    {"name": "💼 Co-Owner",           "color": discord.Color.from_rgb(230, 180, 30),  "hoist": True,  "mentionable": False, "permissions": discord.Permissions(administrator=True)},
    {"name": "⚙️ Developer",          "color": discord.Color.from_rgb(88, 101, 242),  "hoist": True,  "mentionable": False, "permissions": discord.Permissions(administrator=True)},
    {"name": "🛡️ Head Administrator", "color": discord.Color.from_rgb(192, 57, 43),   "hoist": True,  "mentionable": True,  "permissions": discord.Permissions(administrator=True)},
    {"name": "🛡️ Administrator",      "color": discord.Color.from_rgb(231, 76, 60),   "hoist": True,  "mentionable": True,  "permissions": discord.Permissions(administrator=True)},
    {"name": "🔨 Head Moderator",     "color": discord.Color.from_rgb(41, 128, 185),  "hoist": True,  "mentionable": True,  "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True, kick_members=True, ban_members=True, moderate_members=True, manage_channels=True, manage_nicknames=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "🔨 Moderator",          "color": discord.Color.from_rgb(52, 152, 219),  "hoist": True,  "mentionable": True,  "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True, kick_members=True, moderate_members=True, manage_channels=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "🔰 Trial Moderator",    "color": discord.Color.from_rgb(22, 160, 133),  "hoist": True,  "mentionable": True,  "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True, moderate_members=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "🎟️ Support Team",       "color": discord.Color.from_rgb(46, 204, 113),  "hoist": True,  "mentionable": True,  "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "🤝 Helper",             "color": discord.Color.from_rgb(26, 188, 156),  "hoist": True,  "mentionable": True,  "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "🎬 Content Creator",    "color": discord.Color.from_rgb(233, 30, 99),   "hoist": True,  "mentionable": False, "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, add_reactions=True, embed_links=True, attach_files=True, use_application_commands=True, use_external_emojis=True)},
    {"name": "🤝 Partner",            "color": discord.Color.from_rgb(142, 68, 173),  "hoist": True,  "mentionable": False, "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, add_reactions=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "🧪 Beta Tester",        "color": discord.Color.from_rgb(155, 89, 182),  "hoist": True,  "mentionable": False, "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, add_reactions=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "💎 Server Booster",     "color": discord.Color.from_rgb(255, 115, 190), "hoist": True,  "mentionable": False, "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, add_reactions=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "✅ Member",              "color": discord.Color.from_rgb(149, 165, 166), "hoist": False, "mentionable": False, "permissions": discord.Permissions(view_channel=True, send_messages=True, read_message_history=True, add_reactions=True, embed_links=True, attach_files=True, use_application_commands=True)},
    {"name": "🔒 Unverified",         "color": discord.Color.from_rgb(100, 100, 100), "hoist": False, "mentionable": False, "permissions": discord.Permissions.none()},
]

STRUCTURE = [
    {
        "name": "📌 ─── INFORMATION ───",
        "visible_to": ["member", "unverified"],
        "channels": [
            {"name": "📋・rules",        "topic": "Read the rules before participating."},
            {"name": "📢・announcements", "topic": "Official Yoran Studios announcements."},
            {"name": "❓・faq",           "topic": "Frequently asked questions."},
            {"name": "🎟・verification",  "topic": "Click the button below to verify."},
        ],
    },
    {
        "name": "🎮 ─── GAMES ───",
        "visible_to": ["member"],
        "channels": [
            {"name": "🎮・games",         "topic": "Use /games to see everything Yoran Studios is working on."},
            {"name": "📰・devlogs",       "topic": "Development updates for our games."},
            {"name": "🧪・beta-feedback", "topic": "Feedback from beta testers."},
        ],
    },
    {
        "name": "💬 ─── COMMUNITY ───",
        "visible_to": ["member"],
        "channels": [
            {"name": "👋・welcome",       "topic": "Welcome new members!"},
            {"name": "💬・general",       "topic": "General chat — keep it respectful."},
            {"name": "🎨・showcase",      "topic": "Show off your builds, art, and ideas."},
            {"name": "💡・suggestions",   "topic": "Suggest new features or games."},
            {"name": "🪙・economy",       "topic": "Use /daily, /work, /balance and /shop here."},
            {"name": "🧠・trivia",        "topic": "Use /trivia and /tip to learn and earn coins."},
        ],
    },
    {
        "name": "🎫 ─── SUPPORT ───",
        "visible_to": ["member"],
        "channels": [
            {"name": "📩・open-ticket",   "topic": "Click the button to open a support ticket."},
        ],
    },
    {
        "name": "🔒 ─── STAFF ONLY ───",
        "visible_to": [],
        "channels": [
            {"name": "👮・staff-chat",    "topic": "Staff-only discussion."},
            {"name": "📋・mod-logs",      "topic": "Moderation action logs."},
            {"name": "🎮・game-planning", "topic": "Owners/Developers only — unreleased game planning."},
            {"name": "🤖・bot-commands",  "topic": "Bot testing and commands."},
        ],
    },
]

STAFF_ROLE_NAMES = HELPER_ROLES


class SetupConfirmView(discord.ui.View):
    def __init__(self, bot: commands.Bot, invoker: discord.Member):
        super().__init__(timeout=60)
        self.bot = bot
        self.invoker = invoker

    @discord.ui.button(label="Confirm Setup", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the command invoker can confirm.", color=ERROR), ephemeral=True
            )
        self.clear_items()
        await interaction.response.edit_message(
            embed=discord.Embed(title="⚙️  Setting Up Server...", description="Creating roles and channels. Please wait ~30 seconds.", color=PRIMARY),
            view=self,
        )

        guild = interaction.guild
        created_roles: dict[str, discord.Role] = {}

        for role_data in reversed(ROLES):
            try:
                r = await guild.create_role(
                    name=role_data["name"], color=role_data["color"],
                    hoist=role_data["hoist"], mentionable=role_data["mentionable"],
                    permissions=role_data["permissions"],
                )
                created_roles[role_data["name"]] = r
                await asyncio.sleep(0.4)
            except Exception:
                pass

        member_role     = created_roles.get("✅ Member")
        unverified_role = created_roles.get("🔒 Unverified")
        staff_roles     = [created_roles[n] for n in STAFF_ROLE_NAMES if n in created_roles]

        everyone        = guild.default_role
        deny_all        = discord.PermissionOverwrite(view_channel=False)
        staff_full      = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)
        member_read     = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
        member_full     = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        unverified_read = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)

        channels_created = 0
        for cat_data in STRUCTURE:
            try:
                overwrites: dict = {everyone: deny_all}
                for staff_role in staff_roles:
                    overwrites[staff_role] = staff_full
                if "member" in cat_data["visible_to"] and member_role:
                    is_info = cat_data["name"].startswith("📌")
                    overwrites[member_role] = member_read if is_info else member_full
                if "unverified" in cat_data["visible_to"] and unverified_role:
                    overwrites[unverified_role] = unverified_read

                category = await guild.create_category(name=cat_data["name"], overwrites=overwrites)
                await asyncio.sleep(0.5)
                for ch in cat_data["channels"]:
                    await guild.create_text_channel(name=ch["name"], category=category, topic=ch.get("topic", ""))
                    channels_created += 1
                    await asyncio.sleep(0.4)
            except Exception:
                pass

        embed = discord.Embed(
            title="✅  Server Setup Complete",
            description=(
                "All done! Here's what to do next:\n\n"
                "> **1.** Assign yourself the `👑 Owner` role\n"
                "> **2.** Drag my bot role to sit above `✅ Member`/`🔒 Unverified` (Server Settings → Roles)\n"
                "> **3.** Run `/setup-verification` in #verification\n"
                "> **4.** Run `/setup-tickets` in #open-ticket\n"
                "> **5.** Run `/setup-welcome` and `/setup-goodbye` for #welcome\n"
                "> **6.** Use `/gamepanel` (Owner-only) to register your first game"
            ),
            color=SUCCESS,
        )
        embed.add_field(name="📁  Categories", value=f"`{len(STRUCTURE)}`", inline=True)
        embed.add_field(name="💬  Channels",   value=f"`{channels_created}`", inline=True)
        embed.add_field(name="🎭  Roles",      value=f"`{len(created_roles)}`", inline=True)
        embed.set_footer(text="Yoran Studios Quick Setup", icon_url=self.bot.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the invoker can cancel.", color=ERROR), ephemeral=True
            )
        await interaction.response.edit_message(embed=discord.Embed(description="Setup cancelled.", color=ERROR), view=None)


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

    @app_commands.command(name="setup", description="Create Yoran Studios' full role & channel structure (Owner only)")
    @is_owner()
    async def setup_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️  Quick Setup",
            description=(
                "This will automatically create:\n\n"
                f"> ✦ `{len(STRUCTURE)}` Categories with proper permissions\n"
                f"> ✦ `{sum(len(c['channels']) for c in STRUCTURE)}` Channels organized by purpose\n"
                f"> ✦ `{len(ROLES)}` Roles, ranked from `👑 Owner` down to `🔒 Unverified`\n\n"
                "⚠️ This takes about 30 seconds and can't be easily undone."
            ),
            color=WARNING,
        )
        embed.set_footer(text="Yoran Studios Quick Setup", icon_url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, view=SetupConfirmView(self.bot, interaction.user))

    @app_commands.command(name="setup-verification", description="Post the verification panel in a channel")
    @app_commands.describe(channel="Channel to post the verification panel in")
    @is_admin()
    async def setup_verification(self, interaction: discord.Interaction, channel: discord.TextChannel):
        embed = discord.Embed(
            title="🎟️  Member Verification",
            description=(
                f"Welcome to **{interaction.guild.name}**!\n\n"
                "> **1.** Read the server rules\n"
                "> **2.** Press the **Verify** button below\n"
                "> **3.** Instantly unlock the rest of the server\n\n"
                "Having trouble verifying? Open a support ticket and our staff will help you out."
            ),
            color=PRIMARY,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text=f"{interaction.guild.name}  •  Verification", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        await channel.send(embed=embed, view=VerificationView())
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Verification panel posted in {channel.mention}.", color=SUCCESS),
            ephemeral=True,
        )

    @app_commands.command(name="setup-tickets", description="Post the support ticket panel in a channel")
    @app_commands.describe(channel="Channel to post the ticket panel in", category="Category new ticket channels should be created under")
    @is_admin()
    async def setup_tickets(self, interaction: discord.Interaction, channel: discord.TextChannel, category: discord.CategoryChannel = None):
        data = _load_tickets()
        gid = str(interaction.guild.id)
        data.setdefault(gid, {})
        if category:
            data[gid]["category_id"] = category.id
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
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Ticket panel posted in {channel.mention}.", color=SUCCESS),
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
