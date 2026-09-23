"""
main.py — Discord Generator Bot (Python port of index.js)
"""

import asyncio
import os
import sys
import time

# Ensure cogs can import sibling modules
sys.path.insert(0, os.path.dirname(__file__))

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import database as db
import utils

# ── Bot setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guild_messages = True
intents.guilds = True
intents.invites = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ── Invite cache ───────────────────────────────────────────────────────────────
invite_cache: dict[int, dict[str, int]] = {}

ACTIVITY_TYPES = {
    "playing":   discord.ActivityType.playing,
    "watching":  discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}

COGS = [
    "generate",
    "stock",
    "drops",
    "vouches",
    "subscriptions",
    "admin",
    "profile",
    "blacklist",
    "stats",
    "utility",
    "dashboard",
    "community",
]

SUB_ROLE_KEYS = {"free": "role_free", "free+": "role_freeplus", "premium": "role_premium"}

# Guard so one-time startup (sweep loop, command sync) runs exactly once.
_startup_done = False


# ── Helpers ────────────────────────────────────────────────────────────────────

async def apply_presence():
    if not bot.user:
        return
    type_key = (db.get_config("status_type", "playing") or "playing").lower()

    if type_key == "auto":
        try:
            total = sum(db.stock_count(c) for c in utils.CATEGORIES)
        except Exception:
            total = 0
        text = f"{total} account{'s' if total != 1 else ''} in stock"
        act_type = discord.ActivityType.watching
    else:
        text = db.get_config("status_text", "Generator | /generate")
        act_type = ACTIVITY_TYPES.get(type_key, discord.ActivityType.playing)

    try:
        await bot.change_presence(
            activity=discord.Activity(type=act_type, name=text),
            status=discord.Status.online,
        )
    except Exception:
        pass


async def presence_refresh_loop():
    """Keep the live stock-count presence fresh while status_type == 'auto'."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(60)
        if (db.get_config("status_type", "playing") or "playing").lower() == "auto":
            await apply_presence()


async def sweep_expired_subs():
    now = int(time.time())
    try:
        users = db.get_all_users()
    except Exception:
        return
    for u in users:
        if not u or u.get("subscription") in (None, "none"):
            continue
        if not u.get("sub_expires") or u["sub_expires"] == 0:
            continue  # permanent
        if u["sub_expires"] > now:
            continue  # still active
        role_key = SUB_ROLE_KEYS.get(u["subscription"])
        role_id = db.get_config(role_key) if role_key else None
        db.update_user(u["id"], {"subscription": "none", "sub_expires": 0})
        if not role_id:
            continue
        for guild in bot.guilds:
            try:
                member = await guild.fetch_member(int(u["id"]))
            except Exception:
                continue
            role = guild.get_role(int(role_id))
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Subscription expired")
                except Exception:
                    pass


# ── Subscription sweep loop ────────────────────────────────────────────────────

async def sub_sweep_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await sweep_expired_subs()
        await asyncio.sleep(5 * 60)  # every 5 minutes


# ── setup_hook: runs once before login, safe place to load cogs ───────────────

async def setup_hook():
    """Load extensions before the bot connects. Runs exactly once."""
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"  ✓ Loaded {cog}")
        except Exception as exc:
            print(f"  ✗ Failed to load {cog}: {exc}")

    # Sync commands globally once at startup
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as exc:
        print(f"❌ Failed to sync commands: {exc}")


bot.setup_hook = setup_hook


# ── Events ─────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global _startup_done
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")

    # Restore presence on every (re)connect
    await apply_presence()

    # Cache current invites on every (re)connect so the cache stays fresh
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass

    if _startup_done:
        return  # reconnect — skip one-time startup tasks
    _startup_done = True

    # Start background sweep loops exactly once
    bot.loop.create_task(sub_sweep_loop())
    bot.loop.create_task(presence_refresh_loop())

    # Resume drop loop if it was active before restart (delegated to the cog)
    drops_cog = bot.get_cog("Drops")
    if drops_cog and db.get_drop_config("active", "false") == "true":
        drops_cog._start_drop_loop()

    print("✅ Bot is ready!")


@bot.event
async def on_guild_member_add(member: discord.Member):
    """Track which invite was used when a member joins."""
    used = None
    try:
        new_invites = await member.guild.invites()
        cached = invite_cache.get(member.guild.id, {})

        for inv in new_invites:
            if inv.uses > cached.get(inv.code, 0):
                used = inv
                break

        invite_cache[member.guild.id] = {inv.code: inv.uses for inv in new_invites}

        if used and used.inviter:
            db.add_invite_join(str(member.id), str(used.inviter.id), used.code)
    except Exception:
        pass

    # ── Welcome card ─────────────────────────────────────────────────────────
    welcome_channel_id = db.get_config("welcome_channel")
    if not welcome_channel_id:
        return
    try:
        channel = await member.guild.fetch_channel(int(welcome_channel_id))
    except Exception:
        return

    inviter_line = f"<@{used.inviter.id}>" if used and used.inviter else "an unknown invite"
    embed = discord.Embed(
        color=0x57F287,
        title="👋 Welcome to the server!",
        description=(
            f"{member.mention}, glad to have you here!\n\n"
            f"📨 Invited by **{inviter_line}**\n"
            f"👥 You're member **#{member.guild.member_count}**"
        ),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Generator • Use /generate once you have access")
    embed.timestamp = discord.utils.utcnow()
    try:
        await channel.send(embeds=[embed])
    except Exception:
        pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    try:
        db.increment_user_field(str(message.author.id), "messages")
    except Exception:
        pass
    await bot.process_commands(message)


# ── Error handler ──────────────────────────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    embed = discord.Embed(
        color=0xED4245,
        title="⚠️ Command unavailable",
        description="That command could not finish this time. Check the command options and try again.",
    )
    embed.add_field(name="Quick fixes", value="Confirm you have access, try `/help`, or use `/ping` to check bot health.", inline=False)
    embed.set_footer(text="Generator • If this keeps happening, contact the server owner")
    embed.timestamp = discord.utils.utcnow()
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception:
        pass
    print(f"[Command error] {interaction.command}: {error}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("❌ BOT_TOKEN environment variable is not set. Add it as a secret.")
        sys.exit(1)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
