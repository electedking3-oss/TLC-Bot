import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
from typing import Optional
import database as db

with open("config.json") as f:
    CONFIG = json.load(f)

SUCCESS = int(CONFIG["bot"]["success_color"])
ERROR   = int(CONFIG["bot"]["error_color"])
PRIMARY = int(CONFIG["bot"]["color"])


def admin_only():
    async def predicate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", description="Administrator permission required.", color=ERROR
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


class Welcome(commands.Cog):
    """Full welcoming system with custom embeds."""

    def __init__(self, bot):
        self.bot = bot

    def _build_welcome_embed(self, member: discord.Member, config: dict) -> discord.Embed:
        def fmt(text: str) -> str:
            return (text
                    .replace("{user}",    member.mention)
                    .replace("{username}", member.name)
                    .replace("{server}", member.guild.name)
                    .replace("{count}",  str(member.guild.member_count))
                    .replace("{id}",     str(member.id)))

        embed = discord.Embed(
            title=fmt(config.get("title")       or CONFIG["welcome"]["title"]),
            description=fmt(config.get("description") or CONFIG["welcome"]["description"]),
            color=config.get("color") or int(CONFIG["welcome"]["color"]),
            timestamp=datetime.utcnow()
        )

        footer_text = fmt(config.get("footer") or CONFIG["welcome"]["footer"])
        embed.set_footer(text=footer_text)

        if config.get("thumbnail_url"):
            embed.set_thumbnail(url=config["thumbnail_url"])
        else:
            embed.set_thumbnail(url=member.display_avatar.url)

        if config.get("image_url"):
            embed.set_image(url=config["image_url"])

        embed.add_field(name="👤 Member",   value=member.mention,      inline=True)
        embed.add_field(name="🆔 ID",       value=str(member.id),      inline=True)
        embed.add_field(name="📅 Joined",   value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)

        return embed

    # ── on_member_join ────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild

        # Load custom config (db) or fall back to config.json
        db_config = db.get_welcome_config(guild.id) or {}
        if not db_config.get("enabled", CONFIG["welcome"]["enabled"]):
            return

        settings = db.get_guild_settings(guild.id) or {}
        ch_id    = settings.get("welcome_channel")
        channel  = guild.get_channel(ch_id) if ch_id else discord.utils.get(guild.text_channels, name=CONFIG["welcome"]["channel_name"])
        if not channel:
            return

        embed = self._build_welcome_embed(member, db_config)
        await channel.send(embed=embed)

        # DM if configured
        if CONFIG["welcome"].get("dm_on_join"):
            try:
                dm_embed = discord.Embed(
                    title=f"Welcome to {guild.name}!",
                    description=CONFIG["welcome"]["dm_message"].replace("{server}", guild.name),
                    color=PRIMARY
                )
                await member.send(embed=dm_embed)
            except:
                pass

    # ── on_member_remove ──────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not CONFIG["goodbye"]["enabled"]:
            return
        guild    = member.guild
        settings = db.get_guild_settings(guild.id) or {}
        ch_id    = settings.get("goodbye_channel")
        channel  = guild.get_channel(ch_id) if ch_id else discord.utils.get(guild.text_channels, name=CONFIG["goodbye"]["channel_name"])
        if not channel:
            return

        def fmt(text: str) -> str:
            return (text
                    .replace("{user}",    str(member))
                    .replace("{username}", member.name)
                    .replace("{server}", guild.name)
                    .replace("{count}",  str(guild.member_count)))

        embed = discord.Embed(
            title=fmt(CONFIG["goodbye"]["title"]),
            description=fmt(CONFIG["goodbye"]["description"]),
            color=int(CONFIG["goodbye"]["color"]),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="TFF Bot • Goodbye")
        await channel.send(embed=embed)

    # ── /setwelcome ───────────────────────────────────────────────────────────
    @app_commands.command(name="setwelcome", description="Configure the welcome message for new members.")
    @app_commands.describe(
        channel="Channel to send welcome messages",
        title="Embed title ({user}, {server}, {count} supported)",
        description="Embed description",
        image_url="Full banner image URL",
        thumbnail_url="Thumbnail image URL",
        footer="Footer text",
        color="Hex color (e.g. #3498DB)"
    )
    @admin_only()
    async def setwelcome(self, interaction: discord.Interaction,
                          channel: discord.TextChannel,
                          title: str = None,
                          description: str = None,
                          image_url: str = None,
                          thumbnail_url: str = None,
                          footer: str = None,
                          color: str = None):
        await interaction.response.defer(ephemeral=True)

        try:
            color_int = int(color.strip("#"), 16) if color else PRIMARY
        except:
            color_int = PRIMARY

        update = {"enabled": 1}
        if title:         update["title"]         = title
        if description:   update["description"]   = description
        if image_url:     update["image_url"]      = image_url
        if thumbnail_url: update["thumbnail_url"]  = thumbnail_url
        if footer:        update["footer"]         = footer
        if color:         update["color"]          = color_int

        db.upsert_welcome_config(interaction.guild.id, **update)
        db.upsert_guild_settings(interaction.guild.id, welcome_channel=channel.id)

        # Preview
        preview_config = db.get_welcome_config(interaction.guild.id) or {}
        preview_embed  = self._build_welcome_embed(interaction.user, preview_config)
        preview_embed.set_author(name="📋 Preview — Welcome Message")

        await interaction.followup.send(
            content=f"✅ Welcome messages will be sent to {channel.mention}.\n**Preview:**",
            embed=preview_embed,
            ephemeral=True
        )

    # ── /testwelcome ──────────────────────────────────────────────────────────
    @app_commands.command(name="testwelcome", description="Send a test welcome message for yourself.")
    @admin_only()
    async def testwelcome(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild    = interaction.guild
        settings = db.get_guild_settings(guild.id) or {}
        ch_id    = settings.get("welcome_channel")
        channel  = guild.get_channel(ch_id) if ch_id else discord.utils.get(guild.text_channels, name=CONFIG["welcome"]["channel_name"])

        if not channel:
            return await interaction.followup.send(embed=discord.Embed(
                title="❌ No Welcome Channel",
                description="Set a welcome channel first with `/setwelcome`.",
                color=ERROR
            ), ephemeral=True)

        db_config = db.get_welcome_config(guild.id) or {}
        embed     = self._build_welcome_embed(interaction.user, db_config)
        embed.set_author(name="🧪 Test Welcome Message")
        await channel.send(embed=embed)
        await interaction.followup.send("✅ Test message sent!", ephemeral=True)

    # ── /setwelcomeimage ──────────────────────────────────────────────────────
    @app_commands.command(name="setwelcomeimage", description="Set the banner image URL for the welcome embed.")
    @app_commands.describe(url="Direct image URL to use as the banner")
    @admin_only()
    async def setwelcomeimage(self, interaction: discord.Interaction, url: str):
        db.upsert_welcome_config(interaction.guild.id, image_url=url)
        embed = discord.Embed(
            title="✅ Welcome Image Set",
            description="The welcome banner image has been updated.",
            color=SUCCESS
        )
        embed.set_image(url=url)
        embed.set_footer(text="TFF Bot • Welcome System")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /setgoodbyechannel ────────────────────────────────────────────────────
    @app_commands.command(name="setgoodbyechannel", description="Set the goodbye message channel.")
    @app_commands.describe(channel="Channel for goodbye messages")
    @admin_only()
    async def setgoodbyechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.upsert_guild_settings(interaction.guild.id, goodbye_channel=channel.id)
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Goodbye Channel Set",
            description=f"Goodbye messages will be sent to {channel.mention}.",
            color=SUCCESS
        ), ephemeral=True)

    # ── /disablewelcome ───────────────────────────────────────────────────────
    @app_commands.command(name="disablewelcome", description="Disable the welcome message system.")
    @admin_only()
    async def disablewelcome(self, interaction: discord.Interaction):
        db.upsert_welcome_config(interaction.guild.id, enabled=0)
        await interaction.response.send_message(embed=discord.Embed(
            title="🔕 Welcome System Disabled",
            description="New members will no longer receive a welcome message.",
            color=ERROR
        ), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))