import discord
from discord.ext import commands
import json
import os
import asyncio

from config import PRIMARY, SUCCESS, ERROR, WARNING
from utils import HELPER_ROLES as STAFF_ROLES


def _load() -> dict:
    if not os.path.exists("data/tickets.json"):
        return {}
    with open("data/tickets.json", "r") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs("data", exist_ok=True)
    with open("data/tickets.json", "w") as f:
        json.dump(data, f, indent=2)


def _logs_channel(guild: discord.Guild) -> discord.TextChannel | None:
    data = _load()
    ch_id = data.get(str(guild.id), {}).get("logs_channel_id")
    return guild.get_channel(ch_id) if ch_id else None


def _staff_overwrites(guild: discord.Guild, user: discord.Member) -> dict:
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
        ),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True,
        ),
    }
    for role in guild.roles:
        if role.name in STAFF_ROLES:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_messages=True, attach_files=True,
            )
    return overwrites


# ── Ticket open modal ─────────────────────────────────────────────────────────

class TicketOpenModal(discord.ui.Modal, title="🎫 Open a Support Ticket"):
    ticket_type = discord.ui.TextInput(
        label="Ticket Type",
        placeholder="Bug Report / Game Feedback / Suggestion / General Support",
        max_length=100,
    )
    description = discord.ui.TextInput(
        label="Describe your issue",
        style=discord.TextStyle.paragraph,
        placeholder="Tell us what you need help with...",
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild  = interaction.guild
        member = interaction.user
        data   = _load()
        gid    = str(guild.id)

        existing_name = f"ticket-{member.name.lower().replace(' ', '-')}"
        for ch in guild.text_channels:
            if ch.name == existing_name:
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"❌ You already have an open ticket: {ch.mention}", color=WARNING
                    ),
                    ephemeral=True,
                )

        cat_id   = data.get(gid, {}).get("category_id")
        category = guild.get_channel(cat_id) if cat_id else None

        channel = await guild.create_text_channel(
            name=existing_name,
            category=category,
            overwrites=_staff_overwrites(guild, member),
            topic=f"Ticket by {member} ({member.id}) — {self.ticket_type.value}",
        )

        data.setdefault(gid, {}).setdefault("open", {})[str(channel.id)] = str(member.id)
        _save(data)

        embed = discord.Embed(
            title="🎫  Support Ticket",
            color=PRIMARY,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤  Member", value=member.mention, inline=True)
        embed.add_field(name="📋  Type", value=self.ticket_type.value, inline=True)
        embed.add_field(name="📝  Description", value=self.description.value, inline=False)
        embed.add_field(
            name="ℹ️  Info",
            value="> A staff member will be with you shortly.\n> Please be patient and provide any additional details below.",
            inline=False,
        )
        embed.set_footer(text=f"{guild.name}  •  Ticket System", icon_url=guild.icon.url if guild.icon else None)
        embed.timestamp = discord.utils.utcnow()

        await channel.send(content=member.mention, embed=embed, view=TicketControlView())
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Your ticket has been created: {channel.mention}", color=SUCCESS),
            ephemeral=True,
        )

        logs = _logs_channel(guild)
        if logs:
            log_embed = discord.Embed(title="📬  Ticket Opened", color=SUCCESS)
            log_embed.set_thumbnail(url=member.display_avatar.url)
            log_embed.add_field(name="👤  Member", value=f"{member.mention}\n`{member.id}`", inline=True)
            log_embed.add_field(name="📋  Type", value=self.ticket_type.value, inline=True)
            log_embed.add_field(name="💬  Channel", value=channel.mention, inline=True)
            log_embed.add_field(name="📝  Description", value=self.description.value[:1024], inline=False)
            log_embed.timestamp = discord.utils.utcnow()
            try:
                await logs.send(embed=log_embed)
            except discord.HTTPException:
                pass


# ── Views ─────────────────────────────────────────────────────────────────────

class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="yoran:open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketOpenModal())


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="yoran:close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        data   = _load()
        gid    = str(interaction.guild.id)
        ch_id  = str(interaction.channel.id)

        is_staff = any(r.name in STAFF_ROLES for r in member.roles)
        owner_id = data.get(gid, {}).get("open", {}).get(ch_id)
        is_owner = owner_id and str(member.id) == owner_id

        if not is_staff and not is_owner:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only staff or the ticket owner can close this.", color=ERROR),
                ephemeral=True,
            )

        embed = discord.Embed(
            title="🔒  Closing Ticket",
            description=f"Closed by {member.mention}. This channel will be deleted in **5 seconds**.",
            color=ERROR,
        )
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

        if ch_id in data.get(gid, {}).get("open", {}):
            del data[gid]["open"][ch_id]
            _save(data)

        logs = _logs_channel(interaction.guild)
        if logs:
            log_embed = discord.Embed(title="🔒  Ticket Closed", color=ERROR)
            log_embed.set_thumbnail(url=member.display_avatar.url)
            log_embed.add_field(name="💬  Ticket", value=f"`#{interaction.channel.name}`", inline=True)
            log_embed.add_field(name="👤  Opened by", value=f"<@{owner_id}>" if owner_id else "Unknown", inline=True)
            log_embed.add_field(name="🔒  Closed by", value=member.mention, inline=True)
            if interaction.channel.topic:
                log_embed.add_field(name="📋  Details", value=interaction.channel.topic[:1024], inline=False)
            log_embed.timestamp = discord.utils.utcnow()
            try:
                await logs.send(embed=log_embed)
            except discord.HTTPException:
                pass

        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket closed by {member}")

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="✋", custom_id="yoran:ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.name in STAFF_ROLES for r in interaction.user.roles):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only staff can claim tickets.", color=ERROR), ephemeral=True
            )
        embed = discord.Embed(description=f"✋ Ticket claimed by {interaction.user.mention}.", color=SUCCESS)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Add User", style=discord.ButtonStyle.secondary, emoji="➕", custom_id="yoran:ticket_add_user")
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.name in STAFF_ROLES for r in interaction.user.roles):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only staff can add users.", color=ERROR), ephemeral=True
            )
        await interaction.response.send_modal(AddUserModal())


class AddUserModal(discord.ui.Modal, title="Add User to Ticket"):
    user_id = discord.ui.TextInput(
        label="User ID",
        placeholder="Enter the user's Discord ID",
        min_length=17,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            member = await interaction.guild.fetch_member(int(self.user_id.value))
        except Exception:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ User not found.", color=ERROR), ephemeral=True
            )
        await interaction.channel.set_permissions(
            member, view_channel=True, send_messages=True, read_message_history=True
        )
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ {member.mention} has been added to this ticket.", color=SUCCESS)
        )


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketOpenView())
        self.bot.add_view(TicketControlView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
