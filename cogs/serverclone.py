import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR, WARNING
from utils import is_owner

CREATE_DELAY = 0.5   # seconds between create calls to stay under rate limits
EMOJI_DELAY = 1.5    # emoji uploads are rate-limited harder


def _map_overwrites(
    source_overwrites: dict,
    target: discord.Guild,
    role_map: dict[int, discord.Role],
) -> dict:
    """Translate a source channel's permission overwrites to target roles/members."""
    mapped = {}
    for key, ow in source_overwrites.items():
        if isinstance(key, discord.Role):
            if key.is_default():
                mapped[target.default_role] = ow
            elif key.id in role_map:
                mapped[role_map[key.id]] = ow
            # managed/uncloneable roles are skipped
        elif isinstance(key, discord.Member):
            m = target.get_member(key.id)
            if m:
                mapped[m] = ow
    return mapped


class CloneConfirmView(discord.ui.View):
    def __init__(self, cog: "ServerClone", invoker: discord.Member,
                 source: discord.Guild, target: discord.Guild, wipe_target: bool):
        super().__init__(timeout=120)
        self.cog = cog
        self.invoker = invoker
        self.source = source
        self.target = target
        self.wipe_target = wipe_target

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the command invoker can confirm this.", color=ERROR),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm Clone", style=discord.ButtonStyle.danger, emoji="📋")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.clear_items()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="📋  Cloning Server...",
                description="This can take a few minutes. Progress will be posted in this channel.",
                color=PRIMARY,
            ),
            view=self,
        )
        self.stop()
        await self.cog.run_clone(interaction.channel, self.source, self.target, self.wipe_target)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(description="Clone cancelled. Nothing was changed.", color=WARNING), view=None
        )


class ServerClone(commands.Cog):
    """TEMPORARY feature: copy an entire server's structure into another server.

    The SOURCE server is only read — it is never modified. Only the TARGET
    server is written to.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._running: set[int] = set()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You don't have the required role for this command.", color=ERROR),
                ephemeral=True,
            )

    @app_commands.command(
        name="serverclone",
        description="Copy this server's full structure into another server (Owner only)",
    )
    @app_commands.describe(
        target_id="ID of the DESTINATION server (the one that will be overwritten)",
        wipe_target="Delete the destination's existing channels/roles first (default: False)",
    )
    @is_owner()
    async def serverclone(self, interaction: discord.Interaction, target_id: str, wipe_target: bool = False):
        source = interaction.guild

        try:
            target = self.bot.get_guild(int(target_id))
        except ValueError:
            target = None
        if target is None:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ I'm not in that server (or the ID is invalid). Invite me to the destination server first.",
                    color=ERROR,
                ),
                ephemeral=True,
            )
        if target.id == source.id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Source and destination are the same server.", color=ERROR),
                ephemeral=True,
            )
        if not target.me.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ I need **Administrator** permission in **{target.name}**.", color=ERROR),
                ephemeral=True,
            )

        # The invoker must also have power in the DESTINATION server — this
        # prevents cloning over a server that isn't theirs.
        target_member = target.get_member(interaction.user.id)
        if not target_member or not (target_member.guild_permissions.administrator or target.owner_id == interaction.user.id):
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ You must be an administrator (or the owner) of **{target.name}** to clone into it.",
                    color=ERROR,
                ),
                ephemeral=True,
            )
        if target.id in self._running:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ A clone into that server is already in progress.", color=ERROR),
                ephemeral=True,
            )

        embed = discord.Embed(
            title="📋  Clone Server — Confirmation",
            description=(
                f"**Source (read-only, untouched):** {source.name}\n"
                f"**Destination (will be modified):** {target.name} `{target.id}`\n\n"
                "Will copy: roles (permissions, colors, order), categories, text/voice channels "
                "(topics, slowmode, permission overwrites), server name & icon, and emojis (best effort).\n\n"
                + (
                    "⚠️ **wipe_target is ON** — ALL existing channels and roles in the destination "
                    "will be DELETED first. This cannot be undone.\n\n"
                    if wipe_target
                    else "ℹ️ wipe_target is OFF — existing channels/roles in the destination are kept; "
                         "cloned ones are added alongside them.\n\n"
                )
                + "Messages, members, webhooks, and bots are **not** copied."
            ),
            color=WARNING if wipe_target else PRIMARY,
        )
        await interaction.response.send_message(
            embed=embed,
            view=CloneConfirmView(self, interaction.user, source, target, wipe_target),
        )

    async def run_clone(self, channel: discord.TextChannel, source: discord.Guild,
                        target: discord.Guild, wipe_target: bool):
        self._running.add(target.id)
        started = time.time()
        stats = {"roles": 0, "roles_failed": 0, "categories": 0, "channels": 0,
                 "channels_failed": 0, "emojis": 0, "emojis_failed": 0,
                 "wiped_channels": 0, "wiped_roles": 0}

        progress = await channel.send(embed=discord.Embed(description="🧹 Preparing...", color=PRIMARY))

        async def update(text: str):
            try:
                await progress.edit(embed=discord.Embed(description=text, color=PRIMARY))
            except discord.HTTPException:
                pass

        try:
            # ── 1. Optional wipe of destination ────────────────────────────────
            if wipe_target:
                await update("🧹 Wiping destination channels...")
                for ch in list(target.channels):
                    try:
                        await ch.delete(reason="Server clone: wipe target")
                        stats["wiped_channels"] += 1
                        await asyncio.sleep(CREATE_DELAY)
                    except discord.HTTPException:
                        pass
                await update("🧹 Wiping destination roles...")
                for role in list(target.roles):
                    if role.is_default() or role.managed or role >= target.me.top_role:
                        continue
                    try:
                        await role.delete(reason="Server clone: wipe target")
                        stats["wiped_roles"] += 1
                        await asyncio.sleep(CREATE_DELAY)
                    except discord.HTTPException:
                        pass

            # ── 2. Roles ────────────────────────────────────────────────────────
            await update("🎭 Creating roles...")
            role_map: dict[int, discord.Role] = {}
            # skip @everyone and managed roles (bot integrations, booster role)
            source_roles = [r for r in source.roles if not r.is_default() and not r.managed]
            for r in source_roles:
                try:
                    new_role = await target.create_role(
                        name=r.name,
                        permissions=r.permissions,
                        colour=r.colour,
                        hoist=r.hoist,
                        mentionable=r.mentionable,
                        reason=f"Server clone from {source.name}",
                    )
                    role_map[r.id] = new_role
                    stats["roles"] += 1
                    await asyncio.sleep(CREATE_DELAY)
                except discord.HTTPException:
                    stats["roles_failed"] += 1

            # restore hierarchy order (cap below the bot's own top role)
            try:
                ordered = sorted((r for r in source_roles if r.id in role_map), key=lambda r: r.position)
                positions = {role_map[r.id]: i + 1 for i, r in enumerate(ordered)}
                await target.edit_role_positions(positions=positions, reason="Server clone: role order")
            except discord.HTTPException:
                pass

            # @everyone base permissions
            try:
                await target.default_role.edit(permissions=source.default_role.permissions)
            except discord.HTTPException:
                pass

            # ── 3. Categories ───────────────────────────────────────────────────
            await update("📁 Creating categories...")
            cat_map: dict[int, discord.CategoryChannel] = {}
            for cat in sorted(source.categories, key=lambda c: c.position):
                try:
                    new_cat = await target.create_category(
                        name=cat.name,
                        overwrites=_map_overwrites(cat.overwrites, target, role_map),
                        reason=f"Server clone from {source.name}",
                    )
                    cat_map[cat.id] = new_cat
                    stats["categories"] += 1
                    await asyncio.sleep(CREATE_DELAY)
                except discord.HTTPException:
                    stats["channels_failed"] += 1

            # ── 4. Channels ─────────────────────────────────────────────────────
            await update("💬 Creating channels...")

            async def clone_channel(ch: discord.abc.GuildChannel):
                parent = cat_map.get(ch.category_id) if ch.category_id else None
                overwrites = _map_overwrites(ch.overwrites, target, role_map)
                if isinstance(ch, discord.TextChannel):
                    await target.create_text_channel(
                        name=ch.name, topic=ch.topic, nsfw=ch.nsfw,
                        slowmode_delay=ch.slowmode_delay, category=parent,
                        overwrites=overwrites, news=False,
                        reason=f"Server clone from {source.name}",
                    )
                elif isinstance(ch, discord.VoiceChannel):
                    await target.create_voice_channel(
                        name=ch.name, category=parent, overwrites=overwrites,
                        bitrate=min(ch.bitrate, target.bitrate_limit),
                        user_limit=ch.user_limit,
                        reason=f"Server clone from {source.name}",
                    )
                elif isinstance(ch, discord.StageChannel):
                    await target.create_stage_channel(
                        name=ch.name, category=parent, overwrites=overwrites,
                        reason=f"Server clone from {source.name}",
                    )
                elif isinstance(ch, discord.ForumChannel):
                    await target.create_forum(
                        name=ch.name, topic=ch.topic, category=parent,
                        overwrites=overwrites,
                        reason=f"Server clone from {source.name}",
                    )
                else:
                    raise discord.DiscordException(f"Unsupported channel type: {type(ch).__name__}")

            # uncategorized channels first (in order), then per-category (in order)
            uncategorized = [c for c in source.channels
                             if c.category_id is None and not isinstance(c, discord.CategoryChannel)]
            for ch in sorted(uncategorized, key=lambda c: c.position):
                try:
                    await clone_channel(ch)
                    stats["channels"] += 1
                    await asyncio.sleep(CREATE_DELAY)
                except (discord.HTTPException, discord.DiscordException):
                    stats["channels_failed"] += 1

            for cat in sorted(source.categories, key=lambda c: c.position):
                for ch in sorted(cat.channels, key=lambda c: c.position):
                    try:
                        await clone_channel(ch)
                        stats["channels"] += 1
                        await asyncio.sleep(CREATE_DELAY)
                    except (discord.HTTPException, discord.DiscordException):
                        stats["channels_failed"] += 1

            # ── 5. Server name + icon ───────────────────────────────────────────
            await update("🖼️ Copying server name and icon...")
            try:
                icon_bytes = await source.icon.read() if source.icon else None
                await target.edit(name=source.name, icon=icon_bytes, reason=f"Server clone from {source.name}")
            except discord.HTTPException:
                pass

            # ── 6. Emojis (best effort) ─────────────────────────────────────────
            await update("😀 Copying emojis (this is the slow part)...")
            for emoji in source.emojis:
                if len(target.emojis) >= target.emoji_limit:
                    break
                try:
                    img = await emoji.read()
                    await target.create_custom_emoji(name=emoji.name, image=img, reason=f"Server clone from {source.name}")
                    stats["emojis"] += 1
                    await asyncio.sleep(EMOJI_DELAY)
                except discord.HTTPException:
                    stats["emojis_failed"] += 1

            # ── Summary ─────────────────────────────────────────────────────────
            elapsed = int(time.time() - started)
            embed = discord.Embed(title="✅  Server Clone Complete", color=SUCCESS)
            embed.add_field(name="🎭 Roles", value=f"`{stats['roles']}` created" + (f" · `{stats['roles_failed']}` failed" if stats["roles_failed"] else ""), inline=True)
            embed.add_field(name="📁 Categories", value=f"`{stats['categories']}`", inline=True)
            embed.add_field(name="💬 Channels", value=f"`{stats['channels']}` created" + (f" · `{stats['channels_failed']}` failed" if stats["channels_failed"] else ""), inline=True)
            embed.add_field(name="😀 Emojis", value=f"`{stats['emojis']}` copied" + (f" · `{stats['emojis_failed']}` failed" if stats["emojis_failed"] else ""), inline=True)
            if wipe_target:
                embed.add_field(name="🧹 Wiped first", value=f"`{stats['wiped_channels']}` channels · `{stats['wiped_roles']}` roles", inline=True)
            embed.add_field(name="⏱️ Took", value=f"`{elapsed // 60}m {elapsed % 60}s`", inline=True)
            embed.set_footer(text=f"{source.name}  →  {target.name}")
            await progress.edit(embed=embed)

        except Exception as e:
            await progress.edit(embed=discord.Embed(
                title="❌  Clone Failed",
                description=f"Unexpected error: `{type(e).__name__}: {e}`\nWhatever was created so far remains in the destination.",
                color=ERROR,
            ))
        finally:
            self._running.discard(target.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerClone(bot))
