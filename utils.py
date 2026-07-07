from discord import app_commands
import discord

# Rank hierarchy (highest → lowest). Each tier below is a superset of the
# ones above it. Names match the ACTUAL roles in the Yoran Studios server
# (cloned structure, no emojis).
OWNER_ROLES   = {"Owner", "Lead Developer", "Developer"}
ADMIN_ROLES   = OWNER_ROLES | {"Community Manager", "QA Manager", "Administrator", "Highest Staff", "Administration Team"}
MOD_ROLES     = ADMIN_ROLES | {"Trial Administrator", "Senior Moderator", "High Staff", "Moderator"}
SUPPORT_ROLES = MOD_ROLES | {"Trial Moderator", "Moderation Team", "Staff Team"}
HELPER_ROLES  = SUPPORT_ROLES | {"Event Host", "Trial Event Host", "Event Team"}

# Non-staff badge ranks — cosmetic/perk roles, no elevated command access.
COMMUNITY_ROLES = {"Creator", "Contributor", "QA Tester", "OG Tester", "Tester team", "New Tester", "OG Member", "Giveaway Sponsor"}

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
