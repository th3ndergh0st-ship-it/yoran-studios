import json
import os

import discord
from discord.ext import commands

from config import SUCCESS, ERROR, WARNING, INFO
import storage

LOGS_FILE = storage.path("logs.json")

IGNORED_ROLE_NAMES = {"Member", "Unverified"}


def _load() -> dict:
    if not os.path.exists(LOGS_FILE):
        return {}
    with open(LOGS_FILE, "r") as f:
        return json.load(f)


class Logs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _channel(self, guild: discord.Guild, key: str) -> discord.TextChannel | None:
        ch_id = _load().get(str(guild.id), {}).get(key)
        return guild.get_channel(ch_id) if ch_id else None

    async def _send(self, guild: discord.Guild, key: str, embed: discord.Embed):
        channel = self._channel(guild, key)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass


    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        moderator = entry.user
        target = entry.target
        reason = entry.reason or "No reason provided"

        def target_text() -> str:
            tid = getattr(target, "id", None)
            return f"<@{tid}>\n`{tid}`" if tid else "Unknown"

        if entry.action == discord.AuditLogAction.ban:
            embed = discord.Embed(title="🔨  Member Banned", color=ERROR)
            embed.add_field(name="👤 Member", value=target_text(), inline=True)
            embed.add_field(name="🛡️ Moderator", value=moderator.mention if moderator else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=reason, inline=False)
            embed.timestamp = discord.utils.utcnow()
            await self._send(guild, "ban", embed)

        elif entry.action == discord.AuditLogAction.unban:
            embed = discord.Embed(title="✅  Member Unbanned", color=SUCCESS)
            embed.add_field(name="👤 Member", value=target_text(), inline=True)
            embed.add_field(name="🛡️ Moderator", value=moderator.mention if moderator else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=reason, inline=False)
            embed.timestamp = discord.utils.utcnow()
            await self._send(guild, "ban", embed)

        elif entry.action == discord.AuditLogAction.kick:
            embed = discord.Embed(title="👢  Member Kicked", color=WARNING)
            embed.add_field(name="👤 Member", value=target_text(), inline=True)
            embed.add_field(name="🛡️ Moderator", value=moderator.mention if moderator else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=reason, inline=False)
            embed.timestamp = discord.utils.utcnow()
            await self._send(guild, "mod", embed)

        elif entry.action == discord.AuditLogAction.member_update and hasattr(entry.after, "timed_out_until"):
            until = entry.after.timed_out_until
            if until:
                embed = discord.Embed(title="🔇  Member Timed Out", color=WARNING)
                embed.add_field(name="⏰ Until", value=discord.utils.format_dt(until, "R"), inline=True)
            else:
                embed = discord.Embed(title="🔊  Timeout Removed", color=SUCCESS)
            embed.insert_field_at(0, name="👤 Member", value=target_text(), inline=True)
            embed.add_field(name="🛡️ Moderator", value=moderator.mention if moderator else "Unknown", inline=True)
            embed.add_field(name="📋 Reason", value=reason, inline=False)
            embed.timestamp = discord.utils.utcnow()
            await self._send(guild, "mod", embed)

        elif entry.action == discord.AuditLogAction.message_bulk_delete:
            count = getattr(entry.extra, "count", "?")
            embed = discord.Embed(
                title="🗑️  Messages Purged",
                description=f"**{count}** messages deleted in <#{getattr(target, 'id', 0)}>",
                color=WARNING,
            )
            embed.add_field(name="🛡️ Moderator", value=moderator.mention if moderator else "Unknown", inline=True)
            embed.timestamp = discord.utils.utcnow()
            await self._send(guild, "mod", embed)


    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        embed = discord.Embed(title="🗑️  Message Deleted", color=ERROR)
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="💬 Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="👤 Author", value=f"{message.author.mention}\n`{message.author.id}`", inline=True)
        if message.content:
            embed.add_field(name="📝 Content", value=message.content[:1024], inline=False)
        if message.attachments:
            embed.add_field(name="📎 Attachments", value="\n".join(a.url for a in message.attachments)[:1024], inline=False)
        embed.timestamp = discord.utils.utcnow()
        await self._send(message.guild, "action", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        embed = discord.Embed(title="✏️  Message Edited", color=INFO)
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="💬 Channel", value=f"{before.channel.mention}  ·  [Jump]({after.jump_url})", inline=False)
        embed.add_field(name="Before", value=(before.content or "*empty*")[:1024], inline=False)
        embed.add_field(name="After", value=(after.content or "*empty*")[:1024], inline=False)
        embed.timestamp = discord.utils.utcnow()
        await self._send(before.guild, "action", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            embed = discord.Embed(title="🏷️  Nickname Changed", color=INFO)
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.add_field(name="Before", value=f"`{before.nick or before.name}`", inline=True)
            embed.add_field(name="After", value=f"`{after.nick or after.name}`", inline=True)
            embed.timestamp = discord.utils.utcnow()
            await self._send(after.guild, "action", embed)

        if before.roles != after.roles:
            added = [r for r in after.roles if r not in before.roles and r.name not in IGNORED_ROLE_NAMES]
            removed = [r for r in before.roles if r not in after.roles and r.name not in IGNORED_ROLE_NAMES]
            if not added and not removed:
                return
            embed = discord.Embed(title="🎭  Roles Updated", color=INFO)
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            if added:
                embed.add_field(name="➕ Added", value=" ".join(r.mention for r in added)[:1024], inline=False)
            if removed:
                embed.add_field(name="➖ Removed", value=" ".join(r.mention for r in removed)[:1024], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await self._send(after.guild, "action", embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(description=f"➕ Channel created: **{channel.name}** ({channel.mention})", color=SUCCESS)
        embed.timestamp = discord.utils.utcnow()
        await self._send(channel.guild, "action", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        embed = discord.Embed(description=f"➖ Channel deleted: **{channel.name}**", color=ERROR)
        embed.timestamp = discord.utils.utcnow()
        await self._send(channel.guild, "action", embed)


    @commands.Cog.listener()
    async def on_automod_action(self, execution: discord.AutoModAction):
        guild = execution.guild
        if guild is None:
            return
        embed = discord.Embed(title="🤖  AutoMod Triggered", color=WARNING)
        member = execution.member
        embed.add_field(name="👤 Member", value=member.mention if member else f"<@{execution.user_id}>", inline=True)
        if execution.channel_id:
            embed.add_field(name="💬 Channel", value=f"<#{execution.channel_id}>", inline=True)
        embed.add_field(name="⚙️ Rule Trigger", value=str(execution.rule_trigger_type.name), inline=True)
        if execution.matched_keyword:
            embed.add_field(name="🔑 Matched Keyword", value=f"`{execution.matched_keyword}`", inline=True)
        if execution.content:
            embed.add_field(name="📝 Content", value=execution.content[:1024], inline=False)
        embed.timestamp = discord.utils.utcnow()
        await self._send(guild, "automod", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))
