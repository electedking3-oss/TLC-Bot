import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import database as db

with open("config.json") as f:
    CONFIG = json.load(f)

SUCCESS = int(CONFIG["bot"]["success_color"])
ERROR   = int(CONFIG["bot"]["error_color"])
WARNING = int(CONFIG["bot"]["warning_color"])
PRIMARY = int(CONFIG["bot"]["color"])


def admin_only():
    async def predicate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Administrator** permission for this command.",
                color=ERROR
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


class Moderation(commands.Cog):
    """High-level moderation commands for TFF Bot."""

    def __init__(self, bot):
        self.bot = bot
        self.unmute_loop.start()

    def cog_unload(self):
        self.unmute_loop.cancel()

    # ── Helper ────────────────────────────────────────────────────────────────
    async def send_mod_log(self, guild: discord.Guild, embed: discord.Embed):
        settings = db.get_guild_settings(guild.id)
        if not settings or not settings.get("mod_log_id"):
            return
        ch = guild.get_channel(settings["mod_log_id"])
        if ch:
            await ch.send(embed=embed)

    def mod_embed(self, title: str, color: int, **fields) -> discord.Embed:
        embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name.replace("_", " ").title(), value=str(value), inline=True)
        embed.set_footer(text="TFF Bot • Moderation")
        return embed

    # ── /ban ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="Member to ban", reason="Reason for ban", delete_days="Days of messages to delete")
    @admin_only()
    async def ban(self, interaction: discord.Interaction,
                  member: discord.Member,
                  reason: str = "No reason provided",
                  delete_days: int = 0):
        await interaction.response.defer(ephemeral=True)
        if member.top_role >= interaction.user.top_role:
            return await interaction.followup.send(embed=discord.Embed(
                title="❌ Cannot Ban", description="You cannot ban someone with an equal or higher role.", color=ERROR
            ), ephemeral=True)

        try:
            await member.send(embed=discord.Embed(
                title=f"🔨 You've been banned from {interaction.guild.name}",
                description=f"**Reason:** {reason}", color=ERROR
            ))
        except:
            pass

        await member.ban(reason=reason, delete_message_days=delete_days)
        db.log_mod_action(interaction.guild.id, interaction.user.id, "BAN", member.id, reason)

        embed = self.mod_embed("🔨 Member Banned", ERROR,
            member=f"{member} ({member.id})",
            moderator=str(interaction.user),
            reason=reason
        )
        await interaction.followup.send(embed=embed)
        await self.send_mod_log(interaction.guild, embed)

    # ── /unban ────────────────────────────────────────────────────────────────
    @app_commands.command(name="unban", description="Unban a user by their ID.")
    @app_commands.describe(user_id="The user's Discord ID", reason="Reason for unban")
    @admin_only()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        await interaction.response.defer(ephemeral=True)
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)
            db.log_mod_action(interaction.guild.id, interaction.user.id, "UNBAN", user.id, reason)
            embed = self.mod_embed("✅ Member Unbanned", SUCCESS,
                user=f"{user} ({user.id})",
                moderator=str(interaction.user),
                reason=reason
            )
            await interaction.followup.send(embed=embed)
            await self.send_mod_log(interaction.guild, embed)
        except discord.NotFound:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Not Found", description="That user is not banned or the ID is invalid.", color=ERROR
            ), ephemeral=True)

    # ── /kick ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member to kick", reason="Reason for kick")
    @admin_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await interaction.response.defer(ephemeral=True)
        if member.top_role >= interaction.user.top_role:
            return await interaction.followup.send(embed=discord.Embed(
                title="❌ Cannot Kick", description="You cannot kick someone with an equal or higher role.", color=ERROR
            ), ephemeral=True)

        try:
            await member.send(embed=discord.Embed(
                title=f"👢 You've been kicked from {interaction.guild.name}",
                description=f"**Reason:** {reason}", color=WARNING
            ))
        except:
            pass

        await member.kick(reason=reason)
        db.log_mod_action(interaction.guild.id, interaction.user.id, "KICK", member.id, reason)

        embed = self.mod_embed("👢 Member Kicked", WARNING,
            member=f"{member} ({member.id})",
            moderator=str(interaction.user),
            reason=reason
        )
        await interaction.followup.send(embed=embed)
        await self.send_mod_log(interaction.guild, embed)

    # ── /mute ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="mute", description="Mute a member (timeout).")
    @app_commands.describe(member="Member to mute", duration="Duration in minutes", reason="Reason")
    @admin_only()
    async def mute(self, interaction: discord.Interaction,
                   member: discord.Member,
                   duration: int = 60,
                   reason: str = "No reason provided"):
        await interaction.response.defer(ephemeral=True)
        if member.top_role >= interaction.user.top_role:
            return await interaction.followup.send(embed=discord.Embed(
                title="❌ Cannot Mute", description="You cannot mute someone with an equal or higher role.", color=ERROR
            ), ephemeral=True)

        until = datetime.utcnow() + timedelta(minutes=duration)
        await member.timeout(until, reason=reason)

        expires_str = until.strftime("%Y-%m-%d %H:%M:%S")
        db.add_mute(interaction.guild.id, member.id, interaction.user.id, reason, expires_str)
        db.log_mod_action(interaction.guild.id, interaction.user.id, "MUTE", member.id, reason, f"{duration}m")

        embed = self.mod_embed("🔇 Member Muted", WARNING,
            member=f"{member} ({member.id})",
            moderator=str(interaction.user),
            duration=f"{duration} minutes",
            reason=reason,
            expires=f"<t:{int(until.timestamp())}:R>"
        )
        await interaction.followup.send(embed=embed)
        await self.send_mod_log(interaction.guild, embed)

    # ── /unmute ───────────────────────────────────────────────────────────────
    @app_commands.command(name="unmute", description="Remove a timeout from a member.")
    @app_commands.describe(member="Member to unmute", reason="Reason")
    @admin_only()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Manual unmute"):
        await interaction.response.defer(ephemeral=True)
        await member.timeout(None, reason=reason)
        db.remove_mute(interaction.guild.id, member.id)
        db.log_mod_action(interaction.guild.id, interaction.user.id, "UNMUTE", member.id, reason)

        embed = self.mod_embed("🔊 Member Unmuted", SUCCESS,
            member=f"{member} ({member.id})",
            moderator=str(interaction.user),
            reason=reason
        )
        await interaction.followup.send(embed=embed)
        await self.send_mod_log(interaction.guild, embed)

    # ── /warn ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.describe(member="Member to warn", reason="Reason for warning")
    @admin_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await interaction.response.defer(ephemeral=True)
        warn_id = db.add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
        warnings = db.get_warnings(interaction.guild.id, member.id)
        warn_count = len(warnings)
        max_warns = CONFIG["moderation"]["max_warn_before_ban"]

        try:
            await member.send(embed=discord.Embed(
                title=f"⚠️ Warning in {interaction.guild.name}",
                description=f"**Reason:** {reason}\n**Total Warnings:** {warn_count}/{max_warns}",
                color=WARNING
            ))
        except:
            pass

        db.log_mod_action(interaction.guild.id, interaction.user.id, "WARN", member.id, reason)

        embed = self.mod_embed(f"⚠️ Warning Issued (#{warn_id})", WARNING,
            member=f"{member} ({member.id})",
            moderator=str(interaction.user),
            reason=reason,
            total_warnings=f"{warn_count}/{max_warns}"
        )

        if warn_count >= max_warns:
            embed.add_field(name="⚠️ Auto-Action", value=f"Member reached {max_warns} warnings — consider a ban.", inline=False)

        await interaction.followup.send(embed=embed)
        await self.send_mod_log(interaction.guild, embed)

    # ── /warnings ─────────────────────────────────────────────────────────────
    @app_commands.command(name="warnings", description="View all warnings for a member.")
    @app_commands.describe(member="Member to check")
    @admin_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        warns = db.get_warnings(interaction.guild.id, member.id)

        embed = discord.Embed(
            title=f"⚠️ Warnings — {member.display_name}",
            color=WARNING,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="TFF Bot • Moderation")

        if not warns:
            embed.description = "✅ This member has no warnings."
        else:
            for w in warns[:10]:
                embed.add_field(
                    name=f"#{w['id']} — {w['warned_at'][:10]}",
                    value=f"**Reason:** {w['reason']}\n**By:** <@{w['mod_id']}>",
                    inline=False
                )
            if len(warns) > 10:
                embed.set_footer(text=f"Showing 10 of {len(warns)} warnings | TFF Bot")

        await interaction.followup.send(embed=embed)

    # ── /clearwarnings ────────────────────────────────────────────────────────
    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.describe(member="Member to clear warnings for")
    @admin_only()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        count = db.clear_warnings(interaction.guild.id, member.id)
        db.log_mod_action(interaction.guild.id, interaction.user.id, "CLEAR_WARNINGS", member.id, f"Cleared {count} warnings")

        embed = self.mod_embed("🗑️ Warnings Cleared", SUCCESS,
            member=f"{member} ({member.id})",
            moderator=str(interaction.user),
            warnings_cleared=str(count)
        )
        await interaction.followup.send(embed=embed)
        await self.send_mod_log(interaction.guild, embed)

    # ── /purge ────────────────────────────────────────────────────────────────
    @app_commands.command(name="purge", description="Bulk delete messages in a channel.")
    @app_commands.describe(amount="Number of messages to delete (1–100)", member="Only delete messages from this member")
    @admin_only()
    async def purge(self, interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        amount = max(1, min(amount, 100))

        def check(m):
            return member is None or m.author == member

        deleted = await interaction.channel.purge(limit=amount, check=check)
        db.log_mod_action(interaction.guild.id, interaction.user.id, "PURGE", None,
                          f"Deleted {len(deleted)} messages", f"channel:{interaction.channel.id}")

        embed = discord.Embed(
            title="🗑️ Messages Purged",
            description=f"Deleted **{len(deleted)}** messages{f' from {member.mention}' if member else ''}.",
            color=SUCCESS,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="TFF Bot • Moderation")
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.send_mod_log(interaction.guild, embed)

    # ── /slowmode ─────────────────────────────────────────────────────────────
    @app_commands.command(name="slowmode", description="Set slowmode in a channel.")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable)")
    @admin_only()
    async def slowmode(self, interaction: discord.Interaction, seconds: int):
        await interaction.response.defer(ephemeral=True)
        seconds = max(0, min(seconds, 21600))
        await interaction.channel.edit(slowmode_delay=seconds)

        embed = discord.Embed(
            title="⏱️ Slowmode Updated",
            description=f"Slowmode set to **{seconds} seconds** in {interaction.channel.mention}." if seconds > 0 else f"Slowmode **disabled** in {interaction.channel.mention}.",
            color=SUCCESS,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="TFF Bot • Moderation")
        await interaction.followup.send(embed=embed)

    # ── /lockdown ─────────────────────────────────────────────────────────────
    @app_commands.command(name="lockdown", description="Lock or unlock a channel.")
    @app_commands.describe(lock="True to lock, False to unlock", reason="Reason")
    @admin_only()
    async def lockdown(self, interaction: discord.Interaction, lock: bool, reason: str = "Security measure"):
        await interaction.response.defer(ephemeral=True)
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = not lock
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)

        action = "🔒 Locked" if lock else "🔓 Unlocked"
        color  = ERROR if lock else SUCCESS
        embed  = discord.Embed(
            title=f"{action}: {interaction.channel.name}",
            description=f"**Reason:** {reason}\n**By:** {interaction.user.mention}",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="TFF Bot • Moderation")
        await interaction.followup.send(embed=embed)
        await self.send_mod_log(interaction.guild, embed)

    # ── /modlog ───────────────────────────────────────────────────────────────
    @app_commands.command(name="modlog", description="Set the moderation log channel.")
    @app_commands.describe(channel="The channel to send mod logs to")
    @admin_only()
    async def modlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.upsert_guild_settings(interaction.guild.id, mod_log_id=channel.id)
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Mod Log Set",
            description=f"Moderation logs will be sent to {channel.mention}.",
            color=SUCCESS
        ), ephemeral=True)

    # ── Auto Unmute Loop ──────────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def unmute_loop(self):
        expired = db.get_expired_mutes()
        for mute in expired:
            guild = self.bot.get_guild(mute["guild_id"])
            if not guild:
                continue
            member = guild.get_member(mute["user_id"])
            if member:
                try:
                    await member.timeout(None, reason="Mute expired")
                except:
                    pass
            db.remove_mute(mute["guild_id"], mute["user_id"])

    @unmute_loop.before_loop
    async def before_unmute_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Moderation(bot))
