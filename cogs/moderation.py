import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
import json
import os

from config import PRIMARY, SUCCESS, ERROR, WARNING
from utils import is_helper, is_support, is_mod, is_admin, HELPER_ROLES
import storage


def _load_locks() -> dict:
    if not os.path.exists(storage.path("locks.json")):
        return {}
    with open(storage.path("locks.json"), "r") as f:
        return json.load(f)


def _save_locks(data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(storage.path("locks.json"), "w") as f:
        json.dump(data, f, indent=2)


def _load_warns() -> dict:
    if not os.path.exists(storage.path("warnings.json")):
        return {}
    with open(storage.path("warnings.json"), "r") as f:
        return json.load(f)


def _save_warns(data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(storage.path("warnings.json"), "w") as f:
        json.dump(data, f, indent=2)


def _footer(bot: commands.Bot) -> dict:
    return {"text": "Yoran  •  Moderation", "icon_url": bot.user.display_avatar.url}


CASE_EMOJI = {"warn": "⚠️", "timeout": "🔇", "untimeout": "🔊", "kick": "👢",
              "softban": "🧹", "ban": "🔨", "unban": "✅"}


def record_case(guild_id: int, user_id: int, case_type: str, moderator_id: int, reason: str):
    """Append an entry to the member's moderation case history."""
    path = storage.path("cases.json")
    data = {}
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
    data.setdefault(str(guild_id), {}).setdefault(str(user_id), []).append({
        "type": case_type,
        "reason": reason,
        "moderator_id": str(moderator_id),
        "timestamp": discord.utils.utcnow().isoformat(),
    })
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_cases(guild_id: int, user_id: int) -> list[dict]:
    path = storage.path("cases.json")
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f).get(str(guild_id), {}).get(str(user_id), [])


# ── Modals ────────────────────────────────────────────────────────────────────

class BanModal(discord.ui.Modal, title="🔨 Ban Member"):
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="Why are you banning this member?",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, bot, member: discord.Member):
        super().__init__()
        self.bot = bot
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        member, reason = self.member, self.reason.value
        if member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot ban someone with an equal or higher role.", color=ERROR),
                ephemeral=True,
            )
        try:
            await member.send(embed=discord.Embed(
                title="🔨  You have been banned",
                description=f"**Server:** {interaction.guild.name}\n**Reason:** {reason}",
                color=ERROR,
            ))
        except Exception:
            pass
        await member.ban(reason=f"{interaction.user} — {reason}")
        record_case(interaction.guild.id, member.id, "ban", interaction.user.id, reason)
        embed = discord.Embed(title="🔨  Member Banned", color=ERROR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤  Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="🛡️  Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋  Reason", value=reason, inline=False)
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)


class KickModal(discord.ui.Modal, title="👢 Kick Member"):
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="Why are you kicking this member?",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, bot, member: discord.Member):
        super().__init__()
        self.bot = bot
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        member, reason = self.member, self.reason.value
        if member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot kick someone with an equal or higher role.", color=ERROR),
                ephemeral=True,
            )
        try:
            await member.send(embed=discord.Embed(
                title="👢  You have been kicked",
                description=f"**Server:** {interaction.guild.name}\n**Reason:** {reason}",
                color=WARNING,
            ))
        except Exception:
            pass
        await member.kick(reason=f"{interaction.user} — {reason}")
        record_case(interaction.guild.id, member.id, "kick", interaction.user.id, reason)
        embed = discord.Embed(title="👢  Member Kicked", color=WARNING)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤  Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="🛡️  Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋  Reason", value=reason, inline=False)
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)


class SoftbanModal(discord.ui.Modal, title="🧹 Softban Member"):
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="Why are you softbanning this member?",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, bot, member: discord.Member):
        super().__init__()
        self.bot = bot
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        member, reason = self.member, self.reason.value
        if member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot softban someone with an equal or higher role.", color=ERROR),
                ephemeral=True,
            )
        try:
            await member.send(embed=discord.Embed(
                title="🧹  You have been softbanned",
                description=(
                    f"**Server:** {interaction.guild.name}\n**Reason:** {reason}\n\n"
                    "A softban is a kick that also removes your recent messages — you may rejoin with a new invite."
                ),
                color=WARNING,
            ))
        except Exception:
            pass
        # ban to purge the last 24h of messages, then unban right away
        await interaction.guild.ban(member, reason=f"Softban by {interaction.user} — {reason}", delete_message_seconds=86400)
        await interaction.guild.unban(member, reason="Softban release")
        record_case(interaction.guild.id, member.id, "softban", interaction.user.id, reason)
        embed = discord.Embed(title="🧹  Member Softbanned", color=WARNING)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤  Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="🛡️  Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="🗑️  Messages", value="Last 24h deleted", inline=True)
        embed.add_field(name="📋  Reason", value=reason, inline=False)
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)


class WarnModal(discord.ui.Modal, title="⚠️ Warn Member"):
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="Why are you warning this member?",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, bot, member: discord.Member):
        super().__init__()
        self.bot = bot
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        member, reason = self.member, self.reason.value
        data = _load_warns()
        gid, uid = str(interaction.guild.id), str(member.id)
        data.setdefault(gid, {}).setdefault(uid, []).append({
            "reason": reason,
            "moderator_id": str(interaction.user.id),
            "timestamp": discord.utils.utcnow().isoformat(),
        })
        _save_warns(data)
        record_case(interaction.guild.id, member.id, "warn", interaction.user.id, reason)
        count = len(data[gid][uid])
        try:
            await member.send(embed=discord.Embed(
                title="⚠️  You have been warned",
                description=f"**Server:** {interaction.guild.name}\n**Reason:** {reason}\n**Total warnings:** `{count}`",
                color=WARNING,
            ))
        except Exception:
            pass
        embed = discord.Embed(title="⚠️  Member Warned", color=WARNING)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤  Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="🔢  Total Warnings", value=f"`{count}`", inline=True)
        embed.add_field(name="🛡️  Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋  Reason", value=reason, inline=False)
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)


class TimeoutModal(discord.ui.Modal, title="🔇 Timeout Member"):
    minutes = discord.ui.TextInput(
        label="Duration (minutes)",
        placeholder="e.g. 10",
        max_length=6,
    )
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="Why are you timing out this member?",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, bot, member: discord.Member):
        super().__init__()
        self.bot = bot
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        member, reason = self.member, self.reason.value
        try:
            mins = int(self.minutes.value)
            if not (1 <= mins <= 40320):
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Invalid duration. Enter a number between 1 and 40320 minutes.", color=ERROR),
                ephemeral=True,
            )
        if member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot timeout someone with an equal or higher role.", color=ERROR),
                ephemeral=True,
            )
        await member.timeout(timedelta(minutes=mins), reason=f"{interaction.user} — {reason}")
        record_case(interaction.guild.id, member.id, "timeout", interaction.user.id, f"{mins} min — {reason}")
        embed = discord.Embed(title="🔇  Member Timed Out", color=WARNING)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤  Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="⏱️  Duration", value=f"`{mins}` minute(s)", inline=True)
        embed.add_field(name="🛡️  Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋  Reason", value=reason, inline=False)
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Moderation(commands.Cog):
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

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(member="Member to ban")
    @is_mod()
    async def ban(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(BanModal(self.bot, member))

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(member="Member to kick")
    @is_mod()
    async def kick(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(KickModal(self.bot, member))

    @app_commands.command(name="softban", description="Kick a member and delete their last 24h of messages")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(member="Member to softban")
    @is_mod()
    async def softban(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(SoftbanModal(self.bot, member))

    @app_commands.command(name="cases", description="View a member's full moderation history")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member to look up")
    @is_support()
    async def cases(self, interaction: discord.Interaction, member: discord.Member):
        entries = get_cases(interaction.guild.id, member.id)
        embed = discord.Embed(
            title=f"📁  Mod Cases — {member.display_name}",
            color=WARNING if entries else SUCCESS,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if not entries:
            embed.description = "✅ This member has a clean record."
        else:
            for i, case in enumerate(entries[-10:], max(1, len(entries) - 9)):
                emoji = CASE_EMOJI.get(case["type"], "📋")
                mod = interaction.guild.get_member(int(case["moderator_id"]))
                when = case.get("timestamp", "")[:16].replace("T", " ")
                embed.add_field(
                    name=f"{emoji} Case #{i} — {case['type'].upper()}",
                    value=f"**Reason:** {case['reason']}\n**By:** {mod.mention if mod else case['moderator_id']}  ·  `{when} UTC`",
                    inline=False,
                )
            embed.set_footer(text=f"Total: {len(entries)} case(s) — showing the last 10  •  Yoran Moderation")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="Unban a user by their ID")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(user_id="Discord user ID to unban", reason="Reason for unbanning")
    @is_mod()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        await interaction.response.defer(ephemeral=True)
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=f"{interaction.user} — {reason}")
            record_case(interaction.guild.id, user.id, "unban", interaction.user.id, reason)
        except Exception:
            return await interaction.followup.send(
                embed=discord.Embed(description="❌ User not found or not banned.", color=ERROR), ephemeral=True
            )
        embed = discord.Embed(title="✅  User Unbanned", color=SUCCESS)
        embed.add_field(name="👤  User", value=f"{user}\n`{user.id}`", inline=True)
        embed.add_field(name="🛡️  Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="📋  Reason", value=reason, inline=False)
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="timeout", description="Timeout a member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member to timeout")
    @is_support()
    async def timeout(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(TimeoutModal(self.bot, member))

    @app_commands.command(name="untimeout", description="Remove timeout from a member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member to untimeout")
    @is_support()
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        if member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot modify someone with an equal or higher role.", color=ERROR),
                ephemeral=True,
            )
        await member.timeout(None)
        record_case(interaction.guild.id, member.id, "untimeout", interaction.user.id, "Timeout removed")
        embed = discord.Embed(title="🔊  Timeout Removed", color=SUCCESS)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤  Member", value=member.mention, inline=True)
        embed.add_field(name="🛡️  Moderator", value=interaction.user.mention, inline=True)
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member to warn")
    @is_support()
    async def warn(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_modal(WarnModal(self.bot, member))

    @app_commands.command(name="warnings", description="View warnings for a member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member to check")
    @is_helper()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        data = _load_warns()
        warns = data.get(str(interaction.guild.id), {}).get(str(member.id), [])
        embed = discord.Embed(
            title=f"⚠️  Warnings — {member.display_name}",
            color=WARNING if warns else SUCCESS,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if not warns:
            embed.description = "✅ This member has no warnings."
        else:
            for i, w in enumerate(warns, 1):
                mod = interaction.guild.get_member(int(w["moderator_id"]))
                embed.add_field(
                    name=f"Warning #{i}",
                    value=f"**Reason:** {w['reason']}\n**By:** {mod.mention if mod else w['moderator_id']}",
                    inline=False,
                )
        embed.set_footer(text=f"Total: {len(warns)} warning(s)  •  Yoran Moderation")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member to clear warnings for")
    @is_mod()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        data = _load_warns()
        gid, uid = str(interaction.guild.id), str(member.id)
        if gid in data and uid in data[gid]:
            data[gid][uid] = []
            _save_warns(data)
        embed = discord.Embed(
            title="✅  Warnings Cleared",
            description=f"All warnings for {member.mention} have been removed.",
            color=SUCCESS,
        )
        embed.set_footer(**_footer(self.bot))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="purge", description="Delete messages in this channel")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(amount="Number of messages to delete (1–100)", member="Only delete messages from this member")
    @is_support()
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], member: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        # Discord refuses to bulk-delete messages older than 14 days, so let
        # purge() split into bulk + individual deletes as needed.
        deleted = await interaction.channel.purge(
            limit=amount,
            check=lambda msg: member is None or msg.author == member,
            reason=f"Purged by {interaction.user}",
        )
        embed = discord.Embed(
            title="🗑️  Messages Purged",
            description=f"Deleted **{len(deleted)}** message(s){f' from {member.mention}' if member else ''}.",
            color=SUCCESS,
        )
        embed.set_footer(**_footer(self.bot))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="slowmode", description="Set slowmode for this channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(seconds="Seconds between messages — 0 to disable")
    @is_support()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        desc = (
            f"Slowmode **disabled** in {interaction.channel.mention}."
            if seconds == 0
            else f"Slowmode set to **{seconds}s** in {interaction.channel.mention}."
        )
        embed = discord.Embed(title="⏱️  Slowmode Updated", description=desc, color=SUCCESS)
        embed.set_footer(**_footer(self.bot))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lock", description="Lock a channel so members can't send messages")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to lock (defaults to current)", reason="Reason for locking")
    @is_mod()
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "No reason provided"):
        target = channel or interaction.channel
        await interaction.response.defer()
        guild = interaction.guild

        # Denying send for @everyone is not enough: member roles with an
        # explicit send allow on the channel override it. Silence @everyone
        # AND every non-staff role overwrite, snapshotting the previous
        # values so /unlock can restore them exactly.
        roles = [guild.default_role] + [
            t for t in target.overwrites
            if isinstance(t, discord.Role) and not t.is_default() and t.name not in HELPER_ROLES
        ]
        snapshot = {}
        for role in roles:
            ow = target.overwrites_for(role)
            snapshot[str(role.id)] = ow.send_messages
            ow.send_messages = False
            await target.set_permissions(role, overwrite=ow, reason=f"Lock by {interaction.user} — {reason}")

        locks = _load_locks()
        locks.setdefault(str(guild.id), {})[str(target.id)] = snapshot
        _save_locks(locks)

        embed = discord.Embed(
            title="🔒  Channel Locked",
            description=f"{target.mention} has been locked.\n**Reason:** {reason}",
            color=ERROR,
        )
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="unlock", description="Unlock a channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to unlock (defaults to current)", reason="Reason for unlocking")
    @is_mod()
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "No reason provided"):
        target = channel or interaction.channel
        await interaction.response.defer()
        guild = interaction.guild

        locks = _load_locks()
        snapshot = locks.get(str(guild.id), {}).pop(str(target.id), None)
        if snapshot is not None:
            _save_locks(locks)
            # restore each role's send_messages exactly as it was before /lock
            for role_id, previous in snapshot.items():
                role = guild.get_role(int(role_id))
                if role is None:
                    continue
                ow = target.overwrites_for(role)
                ow.send_messages = previous
                if ow.is_empty():
                    await target.set_permissions(role, overwrite=None, reason=f"Unlock by {interaction.user} — {reason}")
                else:
                    await target.set_permissions(role, overwrite=ow, reason=f"Unlock by {interaction.user} — {reason}")
        else:
            # no snapshot (locked before this fix or by hand): neutralize send
            # on @everyone and non-staff role overwrites so defaults apply again
            roles = [guild.default_role] + [
                t for t in target.overwrites
                if isinstance(t, discord.Role) and not t.is_default() and t.name not in HELPER_ROLES
            ]
            for role in roles:
                ow = target.overwrites_for(role)
                if ow.send_messages is False:
                    ow.send_messages = None
                    if ow.is_empty():
                        await target.set_permissions(role, overwrite=None, reason=f"Unlock by {interaction.user} — {reason}")
                    else:
                        await target.set_permissions(role, overwrite=ow, reason=f"Unlock by {interaction.user} — {reason}")

        embed = discord.Embed(
            title="🔓  Channel Unlocked",
            description=f"{target.mention} has been unlocked.\n**Reason:** {reason}",
            color=SUCCESS,
        )
        embed.set_footer(**_footer(self.bot))
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="nick", description="Change a member's nickname")
    @app_commands.default_permissions(manage_nicknames=True)
    @app_commands.describe(member="Member to nickname", nickname="New nickname — leave empty to reset")
    @is_support()
    async def nick(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        before = member.display_name
        await member.edit(nick=nickname)
        embed = discord.Embed(title="✏️  Nickname Changed", color=SUCCESS)
        embed.add_field(name="👤  Member", value=member.mention, inline=True)
        embed.add_field(name="Before", value=f"`{before}`", inline=True)
        embed.add_field(name="After", value=f"`{nickname or member.name}`", inline=True)
        embed.set_footer(**_footer(self.bot))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="role", description="Add or remove a role from a member")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(member="Target member", role="Role to add or remove")
    @is_admin()
    async def role(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ You cannot manage a role equal to or above your own.", color=ERROR),
                ephemeral=True,
            )
        if role in member.roles:
            await member.remove_roles(role)
            action, color = "removed from", WARNING
        else:
            await member.add_roles(role)
            action, color = "added to", SUCCESS
        embed = discord.Embed(
            title="🎭  Role Updated",
            description=f"{role.mention} has been **{action}** {member.mention}.",
            color=color,
        )
        embed.set_footer(**_footer(self.bot))
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
