"""
community.py — Legit voting, vouch analytics, and a shareable server card.
"""

import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils


LEGIT_COLOR = 0x57F287
BRAND_COLOR = 0x5865F2


def _number(value: int) -> str:
    return f"{value:,}"


def _panel_config(guild_id: int) -> dict:
    panels = db.get_config("legit_panels", {}) or {}
    return panels.get(str(guild_id), {})


def _save_panel_config(guild_id: int, config: dict) -> None:
    panels = db.get_config("legit_panels", {}) or {}
    panels[str(guild_id)] = config
    db.set_config("legit_panels", panels)


def _legit_embed(guild: discord.Guild, panel_id: str = None, title: str = None, description: str = None) -> discord.Embed:
    config = _panel_config(guild.id)
    panel_id = panel_id or str(config.get("message_id", ""))
    count = len(db.get_legit_votes(str(guild.id), panel_id)) if panel_id else 0
    embed = discord.Embed(
        color=LEGIT_COLOR,
        title=title or config.get("title") or "🛡️ Is this server legit?",
        description=description or config.get("description") or "If you enjoy the server and trust the community, tap the button below to leave a legit vote.",
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="✅ Legit votes", value=f"**{_number(count)}** member vote(s)", inline=True)
    embed.add_field(name="🔒 Vote policy", value="One vote per member", inline=True)
    embed.add_field(name="💡 Why vote?", value="Your vote helps new members know this community is trusted.", inline=False)
    embed.set_footer(text=f"{guild.name} • Community verification")
    embed.timestamp = discord.utils.utcnow()
    return embed


class LegitVoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Vote Legit", emoji="✅", style=discord.ButtonStyle.success, custom_id="generator:legit_vote")
    async def vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await interaction.response.send_message("This button only works inside a server.", ephemeral=True)
            return
        added = db.add_legit_vote(str(interaction.user.id), str(interaction.guild.id), str(interaction.message.id))
        if not added:
            await interaction.response.send_message("You already voted on this panel. Thanks for supporting the server!", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_legit_embed(interaction.guild, panel_id=str(interaction.message.id)),
            view=self,
        )
        await interaction.followup.send("✅ Your legit vote was counted. Thank you!", ephemeral=True)


class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="legitpanel", description="[Owner] Post a clickable legit-vote panel in a channel.")
    @app_commands.describe(
        channel="Channel where the panel should be posted",
        title="Optional panel title",
        description="Optional message shown above the vote button",
    )
    @app_commands.guild_only()
    async def legitpanel(self, interaction: discord.Interaction, channel: discord.TextChannel,
                         title: str = "🛡️ Is this server legit?",
                         description: str = "If you enjoy the server and trust the community, tap the button below to leave a legit vote."):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        message = await channel.send(
            embed=_legit_embed(interaction.guild, title=title, description=description),
            view=LegitVoteView(),
        )
        _save_panel_config(interaction.guild.id, {
            "channel_id": str(channel.id),
            "message_id": str(message.id),
            "title": title,
            "description": description,
        })
        await message.edit(embed=_legit_embed(interaction.guild, panel_id=str(message.id), title=title, description=description))
        await interaction.followup.send(
            f"✅ Legit vote panel posted in {channel.mention}.\n[Jump to panel]({message.jump_url})",
            ephemeral=True,
        )

    @app_commands.command(name="legitstatus", description="Show the server's current legit vote status.")
    @app_commands.guild_only()
    async def legitstatus(self, interaction: discord.Interaction):
        config = _panel_config(interaction.guild.id)
        panel_id = str(config.get("message_id", ""))
        count = len(db.get_legit_votes(str(interaction.guild.id), panel_id)) if panel_id else 0
        members = interaction.guild.member_count or len(interaction.guild.members) or 1
        percent = min(100, round((count / members) * 100, 1))
        embed = discord.Embed(
            color=LEGIT_COLOR if count else BRAND_COLOR,
            title="🛡️ Server legitimacy",
            description="Community feedback from the live legit-vote panel.",
        )
        embed.add_field(name="✅ Legit votes", value=f"**{_number(count)}**", inline=True)
        embed.add_field(name="📊 Member coverage", value=f"**{percent}%** of members", inline=True)
        embed.add_field(name="📌 Panel", value=f"<#{config.get('channel_id')}>" if config.get("channel_id") else "Not configured", inline=True)
        if config.get("channel_id") and panel_id:
            embed.add_field(name="🔗 Share", value=f"[Open voting panel](https://discord.com/channels/{interaction.guild.id}/{config['channel_id']}/{panel_id})", inline=False)
        embed.set_footer(text="Generator • One vote per member")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="legitreset", description="[Owner] Reset the current server legit-vote count.")
    @app_commands.guild_only()
    async def legitreset(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        config = _panel_config(interaction.guild.id)
        panel_id = str(config.get("message_id", ""))
        removed = db.clear_legit_votes(str(interaction.guild.id), panel_id or None)
        await interaction.response.send_message(
            f"✅ Reset **{_number(removed)}** legit vote(s). The panel will show the new count after the next vote.",
            ephemeral=True,
        )

    @app_commands.command(name="vouchstats", description="Show the server's vouch rating and review breakdown.")
    @app_commands.guild_only()
    async def vouchstats(self, interaction: discord.Interaction):
        vouches = db.get_vouches(100000)
        total = len(vouches)
        stars = [int(v.get("stars", 0) or 0) for v in vouches]
        average = sum(stars) / total if total else 0
        distribution = {star: stars.count(star) for star in range(5, 0, -1)}
        embed = discord.Embed(
            color=0xFEE75C if average >= 4 else BRAND_COLOR,
            title="⭐ Community rating",
            description="A quick summary of the server's written vouches.",
        )
        embed.add_field(name="Average rating", value=f"**{average:.1f} / 5.0**", inline=True)
        embed.add_field(name="Total vouches", value=f"**{_number(total)}**", inline=True)
        embed.add_field(name="Five-star rate", value=f"**{(distribution[5] / total * 100) if total else 0:.0f}%**", inline=True)
        lines = []
        max_count = max(distribution.values(), default=1)
        for star, count in distribution.items():
            bar = utils.progress_bar(count, max_count, length=8)
            lines.append(f"{'⭐' * star}  {bar}  **{_number(count)}**")
        embed.add_field(name="Rating breakdown", value="\n".join(lines), inline=False)
        embed.set_footer(text="Generator • Powered by community vouches")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="servercard", description="Show a shareable overview of this server.")
    @app_commands.guild_only()
    async def servercard(self, interaction: discord.Interaction):
        guild = interaction.guild
        counts = {category: db.stock_count(category) for category in utils.CATEGORIES}
        total_stock = sum(counts.values())
        vouches = db.get_vouches(100000)
        average = sum(int(v.get("stars", 0) or 0) for v in vouches) / len(vouches) if vouches else 0
        config = _panel_config(guild.id)
        votes = len(db.get_legit_votes(str(guild.id), str(config.get("message_id", "")))) if config.get("message_id") else 0
        embed = discord.Embed(
            color=BRAND_COLOR,
            title=f"✨ {guild.name} — Server Card",
            description="A quick, shareable overview of this community.",
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="👥 Members", value=f"**{_number(guild.member_count or len(guild.members))}**", inline=True)
        embed.add_field(name="📦 Stock", value=f"**{_number(total_stock)}** accounts", inline=True)
        embed.add_field(name="🛡️ Legit votes", value=f"**{_number(votes)}**", inline=True)
        embed.add_field(name="⭐ Vouch rating", value=f"**{average:.1f} / 5.0** ({_number(len(vouches))} reviews)", inline=True)
        embed.add_field(name="🟢 Free", value=_number(counts["free"]), inline=True)
        embed.add_field(name="⭐ Premium", value=_number(counts["premium"]), inline=True)
        embed.set_footer(text="Generator • Community overview")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    bot.add_view(LegitVoteView())
    await bot.add_cog(Community(bot))
