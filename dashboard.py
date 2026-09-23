"""
dashboard.py — Live command center, leaderboard, and health tools.
"""

from collections import Counter
import time

import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils


COLORS = {
    "brand": 0x5865F2,
    "success": 0x57F287,
    "warning": 0xFEE75C,
    "danger": 0xED4245,
    "muted": 0x99AAB5,
}

TIER_EMOJI = {"none": "⬜", "free": "🟢", "free+": "🔵", "premium": "⭐"}
TIER_COLORS = {"none": COLORS["muted"], "free": COLORS["success"], "free+": COLORS["brand"], "premium": COLORS["warning"]}


def _number(value: int) -> str:
    return f"{value:,}"


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts[:2])


def _generator_counts() -> Counter:
    return Counter(entry.get("user_id") for entry in db.get_generate_logs(500) if entry.get("user_id"))


class DashboardView(discord.ui.View):
    def __init__(self, cog: "Dashboard", owner_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This dashboard belongs to the person who opened it. Use /dashboard to open your own.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.cog.dashboard_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="My profile", emoji="👤", style=discord.ButtonStyle.secondary)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.profile_embed(interaction.user),
            ephemeral=True,
        )

    @discord.ui.button(label="Commands", emoji="📖", style=discord.ButtonStyle.secondary)
    async def commands(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Use /help for the full command guide, or jump back to /dashboard any time.",
            ephemeral=True,
        )


class Dashboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started_at = time.monotonic()

    def dashboard_embed(self, guild: discord.Guild) -> discord.Embed:
        counts = {category: db.stock_count(category) for category in utils.CATEGORIES}
        total_stock = sum(counts.values())
        stats = db.get_generate_stats()
        users = len(db.get_all_users())
        vouches = len(db.get_vouches(100000))
        embed = discord.Embed(
            color=COLORS["brand"],
            title="⚡ Generator Command Center",
            description=(
                f"A live overview for **{guild.name}**.\n"
                "Use the buttons below for a quick refresh or your personal profile."
            ),
        )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        if guild.icon:
            embed.set_author(name=guild.name, icon_url=guild.icon.url)

        max_stock = max(counts.values(), default=0)
        stock_lines = []
        for category, emoji in (("free", "🟢"), ("free+", "🔵"), ("premium", "⭐")):
            count = counts[category]
            bar = utils.progress_bar(count, max(1, max_stock), length=8)
            stock_lines.append(f"{emoji} **{category.capitalize()}**  `{bar}`  **{_number(count)}**")
        embed.add_field(name=f"📦 Stock  •  {_number(total_stock)} total", value="\n".join(stock_lines), inline=False)
        embed.add_field(
            name="📈 Activity",
            value=(
                f"**{_number(stats['total'])}** generations logged\n"
                f"**{_number(users)}** users tracked\n"
                f"**{_number(vouches)}** vouches collected"
            ),
            inline=True,
        )
        member_count = guild.member_count or len(guild.members)
        embed.add_field(
            name="🌐 Community",
            value=f"**{_number(member_count)}** members\n**{len(guild.channels)}** channels\n**{len(guild.roles)}** roles",
            inline=True,
        )
        top = _generator_counts().most_common(3)
        if top:
            leaders = "\n".join(f"{i}. <@{user_id}> — **{count}**" for i, (user_id, count) in enumerate(top, 1))
        else:
            leaders = "No generations logged yet."
        embed.add_field(name="🏆 Top generators", value=leaders, inline=False)
        embed.add_field(
            name="🚀 Quick actions",
            value="`/generate`  Generate an account\n`/stock`  Check availability\n`/profile`  View your stats\n`/daily`  Claim your daily reward\n`/activity`  View recent trends",
            inline=False,
        )
        embed.set_footer(text="Generator • Live dashboard")
        embed.timestamp = discord.utils.utcnow()
        return embed

    def profile_embed(self, target: discord.abc.User) -> discord.Embed:
        user = db.get_user(str(target.id))
        tier = user.get("subscription", "none")
        counts = _generator_counts()
        generated = counts.get(str(target.id), 0)
        rank = "Unranked"
        if generated:
            rank = f"#{sorted(counts.values(), reverse=True).index(generated) + 1}"
        embed = discord.Embed(
            color=TIER_COLORS.get(tier, COLORS["brand"]),
            title=f"{TIER_EMOJI.get(tier, '⬜')} {target.display_name}",
            description=f"Your generator profile • rank **{rank}**",
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🎟️ Tier", value=tier.capitalize(), inline=True)
        embed.add_field(name="⚡ Generated", value=_number(generated), inline=True)
        embed.add_field(name="🪙 Tokens", value=_number(user.get("tokens", 0)), inline=True)
        embed.add_field(name="💬 Messages", value=_number(user.get("messages", 0)), inline=True)
        embed.add_field(name="📨 Invites", value=_number(db.get_inviter_joins(str(target.id))), inline=True)
        embed.add_field(name="⏳ Subscription", value=utils.format_expires(user.get("sub_expires", 0)), inline=True)
        embed.add_field(name="🔥 Daily streak", value=f"{_number(user.get("daily_streak", 0) or 0)} day(s)", inline=True)
        embed.set_footer(text="Generator • Your activity at a glance")
        embed.timestamp = discord.utils.utcnow()
        return embed


    @app_commands.command(name="daily", description="Claim your daily token reward and build a streak.")
    async def daily(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        user = db.get_user(user_id)
        now = int(time.time())
        last_claim = int(user.get("daily_claimed", 0) or 0)
        cooldown = 86400
        remaining = cooldown - (now - last_claim)

        if last_claim and remaining > 0:
            hours, remainder = divmod(remaining, 3600)
            minutes = remainder // 60
            streak = int(user.get("daily_streak", 0) or 0)
            embed = discord.Embed(
                color=COLORS["warning"],
                title="🕒 Daily reward already claimed",
                description="Your next reward is charging up. Come back when the timer ends.",
            )
            embed.add_field(name="Next claim", value=f"**{hours}h {minutes}m**", inline=True)
            embed.add_field(name="Current streak", value=f"🔥 **{streak} day(s)**", inline=True)
            embed.set_footer(text="Generator • Daily rewards")
            embed.timestamp = discord.utils.utcnow()
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        previous_streak = int(user.get("daily_streak", 0) or 0)
        streak = previous_streak + 1 if last_claim and now - last_claim <= 172800 else 1
        reward = 25 + min(streak - 1, 7) * 5
        new_balance = int(user.get("tokens", 0) or 0) + reward
        db.update_user(user_id, {
            "tokens": new_balance,
            "daily_claimed": now,
            "daily_streak": streak,
        })

        embed = discord.Embed(
            color=COLORS["success"],
            title="🎁 Daily reward claimed!",
            description=f"Nice work, {interaction.user.mention}. Your reward has been added to your balance.",
        )
        embed.add_field(name="Reward", value=f"🪙 **+{_number(reward)} tokens**", inline=True)
        embed.add_field(name="New balance", value=f"🪙 **{_number(new_balance)}**", inline=True)
        embed.add_field(name="Streak", value=f"🔥 **{streak} day(s)**", inline=True)
        embed.set_footer(text="Generator • Return tomorrow to keep your streak alive")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="activity", description="Show recent generation activity and category trends.")
    @app_commands.guild_only()
    async def activity(self, interaction: discord.Interaction):
        now = int(time.time())
        logs = db.get_generate_logs(500)
        recent_24 = [entry for entry in logs if int(entry.get("timestamp", 0) or 0) >= now - 86400]
        recent_7 = [entry for entry in logs if int(entry.get("timestamp", 0) or 0) >= now - 604800]
        category_counts = Counter(entry.get("category", "unknown") for entry in recent_7)
        user_counts = Counter(entry.get("user_id") for entry in recent_7 if entry.get("user_id"))

        embed = discord.Embed(
            color=COLORS["brand"],
            title="📊 Activity Pulse",
            description="A rolling look at how the generator is being used.",
        )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(
            name="⏱️ Last 24 hours",
            value=f"**{_number(len(recent_24))}** generations\n**{_number(len(set(entry.get('user_id') for entry in recent_24 if entry.get('user_id'))))}** active users",
            inline=True,
        )
        embed.add_field(
            name="📅 Last 7 days",
            value=f"**{_number(len(recent_7))}** generations\n**{_number(len(set(entry.get('user_id') for entry in recent_7 if entry.get('user_id'))))}** active users",
            inline=True,
        )
        if category_counts:
            max_category = max(category_counts.values())
            category_lines = []
            for category, count in category_counts.most_common():
                bar = utils.progress_bar(count, max_category, length=8)
                category_lines.append(f"{category.capitalize():<8} {bar} **{_number(count)}**")
            category_value = "\n".join(category_lines)
        else:
            category_value = "No generation activity in the last 7 days."
        embed.add_field(name="📦 Categories • 7 days", value=category_value, inline=False)
        if user_counts:
            leaders = "\n".join(f"{index}. <@{user_id}> — **{_number(count)}**" for index, (user_id, count) in enumerate(user_counts.most_common(5), 1))
        else:
            leaders = "No active generators yet."
        embed.add_field(name="🏆 Most active", value=leaders, inline=False)
        embed.set_footer(text="Generator • Based on the latest 500 logged generations")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dashboard", description="Open the live generator command center.")
    @app_commands.guild_only()
    async def dashboard(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=self.dashboard_embed(interaction.guild),
            view=DashboardView(self, interaction.user.id),
        )

    @app_commands.command(name="leaderboard", description="Show the top account generators.")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction):
        counts = _generator_counts()
        embed = discord.Embed(
            color=COLORS["warning"],
            title="🏆 Generation Leaderboard",
            description="Top generators from the last 500 logged generations.",
        )
        if not counts:
            embed.description = "No generations have been logged yet. Be the first with /generate."
        else:
            top_count = max(counts.values())
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            for index, (user_id, count) in enumerate(counts.most_common(10)):
                prefix = medals[index] if index < 3 else f"`{index + 1:02}`"
                bar = utils.progress_bar(count, top_count, length=8)
                lines.append(f"{prefix} <@{user_id}>  `{bar}`  **{_number(count)}**")
            embed.description = "\n".join(lines)
        embed.set_footer(text="Generator • Rankings update after each generation")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="Check bot latency and uptime.")
    async def ping(self, interaction: discord.Interaction):
        latency = self.bot.latency * 1000
        color = COLORS["success"] if latency < 200 else COLORS["warning"] if latency < 500 else COLORS["danger"]
        embed = discord.Embed(color=color, title="📡 System Health")
        embed.add_field(name="WebSocket", value=f"**{latency:.0f}ms**", inline=True)
        embed.add_field(name="Uptime", value=f"**{_duration(time.monotonic() - self.started_at)}**", inline=True)
        embed.add_field(name="Status", value="🟢 Online", inline=True)
        embed.set_footer(text="Generator • Health check")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))
