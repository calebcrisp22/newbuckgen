"""
utils.py — Access control helpers.
Mirrors utils.js behaviour exactly.
"""

import os
import time
import discord
from database import get_config, get_user

CATEGORIES = ["free", "free+", "premium"]
TIER_RANK = {"none": 0, "free": 1, "free+": 2, "premium": 3}


def is_owner(user_id: str) -> bool:
    return str(user_id) == str(os.environ.get("OWNER_ID", ""))


async def owner_only(interaction: discord.Interaction) -> bool:
    if not is_owner(str(interaction.user.id)):
        embed = discord.Embed(
            color=0xED4245,
            title="❌ No Permission",
            description="Only the bot owner can use this command.",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed], ephemeral=True)
        return False
    return True


def get_category_role_id(category: str):
    return get_config(f"role_{category.replace('+', 'plus')}", None)


def has_active_sub(user_id: str, category: str) -> bool:
    user = get_user(str(user_id))
    if not user.get("subscription") or user["subscription"] == "none":
        return False
    now = int(time.time())
    if user.get("sub_expires", 0) > 0 and user["sub_expires"] < now:
        return False
    return (TIER_RANK.get(user["subscription"], 0)) >= (TIER_RANK.get(category, 99))


def has_generate_access(member: discord.Member, category: str) -> bool:
    if is_owner(str(member.id)):
        return True

    role_id = get_category_role_id(category)
    role_name = "free+" if category == "free+" else category

    if role_id:
        has_role = any(r.id == int(role_id) for r in member.roles)
    else:
        has_role = any(r.name.lower() == role_name.lower() for r in member.roles)

    if category == "free":
        return has_role

    if category == "premium":
        return has_role and has_active_sub(str(member.id), category)

    # free+ (and any future mid-tiers): role OR active subscription
    return has_role or has_active_sub(str(member.id), category)


def progress_bar(value: int, max_value: int, length: int = 10) -> str:
    """Render a filled/empty block progress bar, e.g. ▰▰▰▰▰▱▱▱▱▱."""
    if max_value <= 0:
        ratio = 0.0
    else:
        ratio = max(0.0, min(1.0, value / max_value))
    filled = round(ratio * length)
    return "▰" * filled + "▱" * (length - filled)


def format_expires(ts: int) -> str:
    """Return a human-readable expiry string."""
    if ts == 0:
        return "Never (permanent)"
    remaining = ts - int(time.time())
    if remaining <= 0:
        return "Expired"
    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "< 1m"
