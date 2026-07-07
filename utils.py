from discord import app_commands
import discord

# Rank hierarchy (highest → lowest). Each tier below is a superset of the
# ones above it, mirroring the actual Discord role order created by /setup.
OWNER_ROLES   = {"👑 Owner", "💼 Co-Owner", "⚙️ Developer"}
ADMIN_ROLES   = OWNER_ROLES | {"🛡️ Head Administrator", "🛡️ Administrator"}
MOD_ROLES     = ADMIN_ROLES | {"🔨 Head Moderator", "🔨 Moderator"}
SUPPORT_ROLES = MOD_ROLES | {"🔰 Trial Moderator", "🎟️ Support Team"}
HELPER_ROLES  = SUPPORT_ROLES | {"🤝 Helper"}

# Non-staff badge ranks — cosmetic/perk roles, no elevated command access.
COMMUNITY_ROLES = {"🎬 Content Creator", "🤝 Partner", "🧪 Beta Tester", "💎 Server Booster"}

# Hardcoded ID for the top "owner owner" role — matched by ID instead of name
# so it keeps working even if the role gets renamed. Bypasses every check.
SUPER_OWNER_ROLE_IDS = {1523445699377627186, 1230234714229444623}

# User accounts that bypass every check in ANY server the bot is in
# (role checks are per-server; these follow the person instead).
SUPER_OWNER_USER_IDS = {1230234714229444623}


def _has_any(interaction: discord.Interaction, names: set) -> bool:
    # The real Discord server owner (the 👑 next to their name in the member
    # list) always passes every check — even before /setup has created any
    # of the custom rank roles above. Without this, the actual owner would
    # be locked out of running /setup itself on a fresh server.
    if interaction.user.id in SUPER_OWNER_USER_IDS:
        return True
    if interaction.guild and interaction.user.id == interaction.guild.owner_id:
        return True
    if any(r.id in SUPER_OWNER_ROLE_IDS for r in interaction.user.roles):
        return True
    return any(r.name in names for r in interaction.user.roles)


def is_helper():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _has_any(interaction, HELPER_ROLES):
            return True
        raise app_commands.CheckFailure("helper_role")
    return app_commands.check(predicate)


def is_support():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _has_any(interaction, SUPPORT_ROLES):
            return True
        raise app_commands.CheckFailure("support_role")
    return app_commands.check(predicate)


def is_mod():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _has_any(interaction, MOD_ROLES):
            return True
        raise app_commands.CheckFailure("moderator_role")
    return app_commands.check(predicate)


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _has_any(interaction, ADMIN_ROLES):
            return True
        raise app_commands.CheckFailure("administrator_role")
    return app_commands.check(predicate)


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _has_any(interaction, OWNER_ROLES):
            return True
        raise app_commands.CheckFailure("owner_role")
    return app_commands.check(predicate)
