import json
import os
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import PRIMARY, SUCCESS, ERROR
import storage

YT_CHANNEL_URL = "https://www.youtube.com/@YoranStudio"
REWARD_ROLE_ID = 1526375014876713142
REWARD_ROLE_NAME = "Follower"
VERIFY_TTL_DAYS = 30

SUBMIT_CHANNEL_NAME = "✅・verify-sub"
REVIEW_CHANNEL_NAME = "📩・sub-reviews"

CONFIG_FILE = storage.path("verifysub.json")
VERIFIED_FILE = storage.path("yt_verified.json")


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(path: str, data: dict):
    os.makedirs(storage.DATA_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _clear_pending(guild_id: int, user_id: int):
    data = _load(CONFIG_FILE)
    data.get(str(guild_id), {}).get("pending", {}).pop(str(user_id), None)
    _save(CONFIG_FILE, data)


def _uid_from_review_message(message: discord.Message) -> int | None:
    """The reviewed member's ID travels in the embed footer as 'UID:<id>'."""
    if not message.embeds or not message.embeds[0].footer or not message.embeds[0].footer.text:
        return None
    text = message.embeds[0].footer.text
    if "UID:" not in text:
        return None
    try:
        return int(text.split("UID:")[1].strip())
    except ValueError:
        return None


async def _ensure_reward_role(guild: discord.Guild) -> discord.Role | None:
    return guild.get_role(REWARD_ROLE_ID) or discord.utils.get(guild.roles, name=REWARD_ROLE_NAME)


async def _finish_review(message: discord.Message, approved: bool, reviewer: discord.Member, note: str = ""):
    try:
        await message.delete()
    except discord.HTTPException:
        pass


def _is_reviewer(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


class DeclineNoteModal(discord.ui.Modal, title="❌ Decline Verification"):
    note = discord.ui.TextInput(
        label="Note for the member (optional)",
        placeholder="e.g. The screenshot doesn't show your account is subscribed",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(self, target_id: int, review_message: discord.Message):
        super().__init__()
        self.target_id = target_id
        self.review_message = review_message

    async def on_submit(self, interaction: discord.Interaction):
        note = self.note.value.strip()
        _clear_pending(interaction.guild.id, self.target_id)
        await _finish_review(self.review_message, False, interaction.user, note)

        user = interaction.client.get_user(self.target_id)
        if user:
            try:
                desc = (
                    f"Your YouTube subscription verification in **{interaction.guild.name}** was **declined**.\n"
                    + (f"\n📝 **Staff note:** {note}\n" if note else "")
                    + f"\nMake sure you're subscribed and try again:\n### 🔴 [Subscribe to YoranStudio]({YT_CHANNEL_URL})"
                )
                await user.send(embed=discord.Embed(title="❌  Verification Declined", description=desc, color=ERROR))
            except discord.HTTPException:
                pass
        await interaction.response.send_message(
            embed=discord.Embed(description="❌ Request declined — the member was notified by DM.", color=ERROR),
            ephemeral=True,
        )


class SubReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id="yoran:sub_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_reviewer(interaction.user):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only admins can review verifications.", color=ERROR), ephemeral=True
            )
        uid = _uid_from_review_message(interaction.message)
        if uid is None:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Couldn't read the member ID from this request.", color=ERROR), ephemeral=True
            )
        guild = interaction.guild
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except discord.HTTPException:
                _clear_pending(guild.id, uid)
                await _finish_review(interaction.message, False, interaction.user, "Member left the server")
                return await interaction.response.send_message(
                    embed=discord.Embed(description="❌ That member is no longer in the server.", color=ERROR), ephemeral=True
                )

        role = await _ensure_reward_role(guild)
        if role is None:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ The **Follower** role no longer exists — restore it before approving.", color=ERROR),
                ephemeral=True,
            )
        try:
            await member.add_roles(role, reason=f"YouTube sub verified manually by {interaction.user}")
        except discord.HTTPException:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ I couldn't assign the reward role — check my role position.", color=ERROR),
                ephemeral=True,
            )

        verified = _load(VERIFIED_FILE)
        verified[str(uid)] = time.time()
        _save(VERIFIED_FILE, verified)
        _clear_pending(guild.id, uid)
        await _finish_review(interaction.message, True, interaction.user)

        submit_ch = guild.get_channel(_load(CONFIG_FILE).get(str(guild.id), {}).get("submit"))
        if submit_ch:
            try:
                await submit_ch.set_permissions(member, view_channel=False, reason="Follower verified — verify-sub hidden")
            except discord.HTTPException:
                pass

        try:
            await member.send(embed=discord.Embed(
                title="✅  Verification Approved",
                description=(
                    f"Your YouTube subscription in **{guild.name}** was confirmed! 🎉\n"
                    + (f"You now have the **{role.name}** role.\n\n" if role else "\n")
                    + f"ℹ️ Verification lasts **{VERIFY_TTL_DAYS} days** — you'll be asked to re-verify after that."
                ),
                color=SUCCESS,
            ))
        except discord.HTTPException:
            pass
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Approved — {member.mention} got their role and was notified by DM.", color=SUCCESS),
            ephemeral=True,
        )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌", custom_id="yoran:sub_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_reviewer(interaction.user):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only admins can review verifications.", color=ERROR), ephemeral=True
            )
        uid = _uid_from_review_message(interaction.message)
        if uid is None:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Couldn't read the member ID from this request.", color=ERROR), ephemeral=True
            )
        await interaction.response.send_modal(DeclineNoteModal(uid, interaction.message))


class VerifySub(commands.Cog):
    """Manual YouTube subscription verification: screenshot in a dedicated
    channel, admin review with Accept/Decline, results by DM."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(SubReviewView())
        self.expire_verifications.start()

    async def cog_unload(self):
        self.expire_verifications.cancel()

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


    @tasks.loop(hours=12)
    async def expire_verifications(self):
        data = _load(VERIFIED_FILE)
        now = time.time()
        ttl = VERIFY_TTL_DAYS * 86400
        changed = False

        for user_id, verified_at in list(data.items()):
            if now - verified_at < ttl:
                continue
            removed = False
            for guild in self.bot.guilds:
                member = guild.get_member(int(user_id))
                role = guild.get_role(REWARD_ROLE_ID) or discord.utils.get(guild.roles, name=REWARD_ROLE_NAME)
                if member and role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="YouTube verification expired (re-verify required)")
                        removed = True
                    except discord.HTTPException:
                        pass
                    submit_ch = guild.get_channel(_load(CONFIG_FILE).get(str(guild.id), {}).get("submit"))
                    if submit_ch:
                        try:
                            await submit_ch.set_permissions(member, overwrite=None, reason="Verification expired — verify-sub visible again")
                        except discord.HTTPException:
                            pass
            del data[user_id]
            changed = True

            if removed:
                user = self.bot.get_user(int(user_id))
                if user:
                    try:
                        await user.send(embed=discord.Embed(
                            title="⏰  Verification Expired",
                            description=(
                                "Your YouTube subscriber perks expired and the role was removed.\n\n"
                                "Still subscribed? Just run `/verifysub` again with a screenshot!\n\n"
                                f"### 🔴 [Subscribe to YoranStudio]({YT_CHANNEL_URL})"
                            ),
                            color=ERROR,
                        ))
                    except discord.HTTPException:
                        pass

        if changed:
            _save(VERIFIED_FILE, data)

    @expire_verifications.before_loop
    async def before_expire(self):
        await self.bot.wait_until_ready()


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        cfg = _load(CONFIG_FILE).get(str(message.guild.id), {})
        if message.channel.id == cfg.get("submit"):
            try:
                await message.delete()
            except discord.HTTPException:
                pass


    @app_commands.command(name="verifysub", description="Verify your YouTube subscription by submitting a screenshot")
    @app_commands.describe(screenshot="Screenshot proving you're subscribed to the channel")
    async def verifysub(self, interaction: discord.Interaction, screenshot: discord.Attachment):
        guild = interaction.guild
        cfg = _load(CONFIG_FILE).get(str(guild.id), {})
        submit_id, review_id = cfg.get("submit"), cfg.get("review")

        if not submit_id or not review_id:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Verification isn't configured on this server — contact staff.", color=ERROR),
                ephemeral=True,
            )
        if interaction.channel_id != submit_id:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ This command only works in <#{submit_id}>.", color=ERROR),
                ephemeral=True,
            )
        if not (screenshot.content_type or "").startswith("image/"):
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Please attach an **image** (screenshot of your subscription).", color=ERROR),
                ephemeral=True,
            )

        role = guild.get_role(REWARD_ROLE_ID) or discord.utils.get(guild.roles, name=REWARD_ROLE_NAME)
        if role and role in interaction.user.roles:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"✅ You already have the **{role.name}** role!", color=SUCCESS),
                ephemeral=True,
            )

        data = _load(CONFIG_FILE)
        pending = data.setdefault(str(guild.id), {}).setdefault("pending", {})
        if str(interaction.user.id) in pending:
            return await interaction.response.send_message(
                embed=discord.Embed(description="⏳ You already have a pending request — please wait for staff to review it.", color=ERROR),
                ephemeral=True,
            )

        review_channel = guild.get_channel(review_id)
        if review_channel is None:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ The review channel no longer exists — contact staff.", color=ERROR),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        file = await screenshot.to_file()
        embed = discord.Embed(
            title="📩  Subscription Verification Request",
            description="Use the buttons below to approve or decline.",
            color=PRIMARY,
        )
        embed.add_field(name="👤 Member", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
        embed.set_image(url=f"attachment://{file.filename}")
        embed.set_footer(text=f"UID:{interaction.user.id}")
        embed.timestamp = discord.utils.utcnow()
        msg = await review_channel.send(embed=embed, file=file, view=SubReviewView())

        pending[str(interaction.user.id)] = msg.id
        _save(CONFIG_FILE, data)

        await interaction.followup.send(
            embed=discord.Embed(
                description="✅ Your request was submitted! Staff will review it and you'll get the result by **DM**.",
                color=SUCCESS,
            ),
            ephemeral=True,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(VerifySub(bot))
