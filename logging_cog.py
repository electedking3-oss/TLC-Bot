import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
from typing import Optional
import database as db

with open("config.json") as f:
    CONFIG = json.load(f)

LOG_CFG = CONFIG["logging"]
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


class Logging(commands.Cog):
    """Full-level logging for every server action."""

    def __init__(self, bot):
        self.bot = bot

    # ── Helper ────────────────────────────────────────────────────────────────
    async def get_log_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        if not LOG_CFG["enabled"]:
            return None
        settings = db.get_guild_settings(guild.id)
        if not settings or not settings.get("log_channel_id"):
            return None
        return guild.get_channel(settings["log_channel_id"])

    def log_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
        embed.set_footer(text="TFF Bot • Full Logging")
        return embed

    # ── /setlogchannel ────────────────────────────────────────────────────────
    @app_commands.command(name="setlogchannel", description="Set the channel for full server logs.")
    @app_commands.describe(channel="The logging channel")
    @admin_only()
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.upsert_guild_settings(interaction.guild.id, log_channel_id=channel.id)
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Log Channel Set",
            description=f"All server logs will be sent to {channel.mention}.",
            color=SUCCESS
        ), ephemeral=True)

    # ── Message Delete ────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not LOG_CFG.get("log_message_deletes"):
            return
        ch = await self.get_log_channel(message.guild)
        if not ch:
            return

        embed = self.log_embed("🗑️ Message Deleted", 0xE74C3C)
        embed.add_field(name="Author",  value=f"{message.author.mention} ({message.author.id})", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        content = message.content or "*[No text content]*"
        if len(content) > 1000:
            content = content[:1000] + "..."
        embed.add_field(name="Content", value=content, inline=False)
        if message.attachments:
            embed.add_field(name="Attachments", value="\n".join(a.filename for a in message.attachments), inline=False)
        await ch.send(embed=embed)

    # ── Message Edit ──────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        if not LOG_CFG.get("log_message_edits"):
            return
        ch = await self.get_log_channel(before.guild)
        if not ch:
            return

        embed = self.log_embed("✏️ Message Edited", 0xF39C12)
        embed.add_field(name="Author",  value=f"{before.author.mention} ({before.author.id})", inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Jump",    value=f"[View Message]({after.jump_url})", inline=True)
        before_c = (before.content or "*empty*")[:500]
        after_c  = (after.content  or "*empty*")[:500]
        embed.add_field(name="Before", value=before_c, inline=False)
        embed.add_field(name="After",  value=after_c,  inline=False)
        await ch.send(embed=embed)

    # ── Member Join ───────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not LOG_CFG.get("log_member_joins"):
            return
        ch = await self.get_log_channel(member.guild)
        if not ch:
            return

        account_age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
        embed = self.log_embed("📥 Member Joined", 0x2ECC71)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member",      value=f"{member.mention} ({member.id})", inline=True)
        embed.add_field(name="Account Age", value=f"{account_age} days", inline=True)
        embed.add_field(name="Total Members", value=str(member.guild.member_count), inline=True)
        if account_age < 7:
            embed.add_field(name="⚠️ Warning", value="New account — less than 7 days old.", inline=False)
        await ch.send(embed=embed)

    # ── Member Leave ──────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not LOG_CFG.get("log_member_leaves"):
            return
        ch = await self.get_log_channel(member.guild)
        if not ch:
            return

        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        embed = self.log_embed("📤 Member Left", 0xE74C3C)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
        embed.add_field(name="Total Members", value=str(member.guild.member_count), inline=True)
        if roles:
            embed.add_field(name="Roles", value=" ".join(roles[:10]) or "None", inline=False)
        await ch.send(embed=embed)

    # ── Role Changes ──────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not before.guild:
            return

        ch = await self.get_log_channel(before.guild)
        if not ch:
            return

        # Role changes
        if LOG_CFG.get("log_role_changes") and before.roles != after.roles:
            added   = [r for r in after.roles  if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added or removed:
                embed = self.log_embed("🔄 Member Roles Updated", 0x9B59B6)
                embed.add_field(name="Member", value=f"{after.mention} ({after.id})", inline=True)
                if added:
                    embed.add_field(name="Roles Added",   value=" ".join(r.mention for r in added),   inline=False)
                if removed:
                    embed.add_field(name="Roles Removed", value=" ".join(r.mention for r in removed), inline=False)
                await ch.send(embed=embed)

        # Nickname changes
        if LOG_CFG.get("log_nickname_changes") and before.nick != after.nick:
            embed = self.log_embed("📝 Nickname Changed", 0x3498DB)
            embed.add_field(name="Member",   value=f"{after.mention} ({after.id})", inline=True)
            embed.add_field(name="Before",   value=before.nick or "*None*", inline=True)
            embed.add_field(name="After",    value=after.nick  or "*None*", inline=True)
            await ch.send(embed=embed)

    # ── Emoji Create/Delete ───────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        if not LOG_CFG.get("log_emoji_changes"):
            return
        ch = await self.get_log_channel(guild)
        if not ch:
            return

        before_set = set(before)
        after_set  = set(after)
        added   = after_set - before_set
        removed = before_set - after_set

        if added:
            embed = self.log_embed("😀 Emoji Added", 0x2ECC71)
            embed.add_field(name="Emoji(s)", value=" ".join(str(e) for e in added), inline=False)
            await ch.send(embed=embed)

        if removed:
            embed = self.log_embed("🗑️ Emoji Deleted", 0xE74C3C)
            embed.add_field(name="Emoji(s)", value=", ".join(e.name for e in removed), inline=False)
            await ch.send(embed=embed)

    # ── Channel Create/Delete ─────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if not LOG_CFG.get("log_channel_changes"):
            return
        ch = await self.get_log_channel(channel.guild)
        if not ch:
            return

        embed = self.log_embed("📢 Channel Created", 0x2ECC71)
        embed.add_field(name="Channel", value=f"{channel.mention} (`{channel.name}`)", inline=True)
        embed.add_field(name="Type",    value=str(channel.type).replace("_", " ").title(), inline=True)
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if not LOG_CFG.get("log_channel_changes"):
            return
        ch = await self.get_log_channel(channel.guild)
        if not ch:
            return

        embed = self.log_embed("🗑️ Channel Deleted", 0xE74C3C)
        embed.add_field(name="Name", value=f"`{channel.name}`", inline=True)
        embed.add_field(name="Type", value=str(channel.type).replace("_", " ").title(), inline=True)
        await ch.send(embed=embed)

    # ── Voice Activity ────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not LOG_CFG.get("log_voice_activity"):
            return
        ch = await self.get_log_channel(member.guild)
        if not ch:
            return

        if before.channel is None and after.channel is not None:
            embed = self.log_embed("🔊 Joined Voice", 0x2ECC71)
            embed.add_field(name="Member",  value=f"{member.mention} ({member.id})", inline=True)
            embed.add_field(name="Channel", value=after.channel.mention, inline=True)
            await ch.send(embed=embed)
        elif before.channel is not None and after.channel is None:
            embed = self.log_embed("🔇 Left Voice", 0xE74C3C)
            embed.add_field(name="Member",  value=f"{member.mention} ({member.id})", inline=True)
            embed.add_field(name="Channel", value=before.channel.mention, inline=True)
            await ch.send(embed=embed)
        elif before.channel != after.channel:
            embed = self.log_embed("🔀 Moved Voice Channel", 0xF39C12)
            embed.add_field(name="Member", value=f"{member.mention} ({member.id})", inline=True)
            embed.add_field(name="From",   value=before.channel.mention, inline=True)
            embed.add_field(name="To",     value=after.channel.mention,  inline=True)
            await ch.send(embed=embed)

    # ── Ban / Unban ───────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        ch = await self.get_log_channel(guild)
        if not ch:
            return
        embed = self.log_embed("🔨 Member Banned", 0xE74C3C)
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        ch = await self.get_log_channel(guild)
        if not ch:
            return
        embed = self.log_embed("✅ Member Unbanned", 0x2ECC71)
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)
        await ch.send(embed=embed)

    # ── Guild Update ──────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        ch = await self.get_log_channel(after)
        if not ch:
            return

        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** `{before.name}` → `{after.name}`")
        if before.icon != after.icon:
            changes.append("**Icon** was changed.")
        if before.description != after.description:
            changes.append("**Description** was changed.")
        if before.verification_level != after.verification_level:
            changes.append(f"**Verification Level:** `{before.verification_level}` → `{after.verification_level}`")

        if changes:
            embed = self.log_embed("⚙️ Server Updated", 0x9B59B6, "\n".join(changes))
            await ch.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Logging(bot))