import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import random
import string
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
import database as db

with open("config.json") as f:
    CONFIG = json.load(f)

SUCCESS = int(CONFIG["bot"]["success_color"])
ERROR   = int(CONFIG["bot"]["error_color"])
WARNING = int(CONFIG["bot"]["warning_color"])
PRIMARY = int(CONFIG["bot"]["color"])

SPAM_CFG  = CONFIG["security"]["anti_spam"]
RAID_CFG  = CONFIG["security"]["anti_raid"]
VERIFY_CFG = CONFIG["security"]["verification"]


def admin_only():
    async def predicate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="You need **Administrator** permission.",
                color=ERROR
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


class Security(commands.Cog):
    """Anti-Spam, Anti-Raid, and Verification for TFF Bot."""

    def __init__(self, bot):
        self.bot = bot
        # {guild_id: {user_id: [timestamps]}}
        self._spam_tracker: dict = defaultdict(lambda: defaultdict(list))
        # {guild_id: [join_timestamps]}
        self._join_tracker: dict = defaultdict(list)
        # Guilds currently in lockdown
        self._lockdown_guilds: set = set()
        self.cleanup_spam.start()

    def cog_unload(self):
        self.cleanup_spam.cancel()

    # ── Generate Captcha Code ─────────────────────────────────────────────────
    def _gen_code(self, length: int = 6) -> str:
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

    # ── Anti-Spam: on_message ─────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not SPAM_CFG["enabled"]:
            return
        if message.author.guild_permissions.administrator:
            return

        gid = message.guild.id
        uid = message.author.id
        now = datetime.utcnow()
        window = SPAM_CFG["time_window_seconds"]
        max_msgs = SPAM_CFG["max_messages"]

        timestamps = self._spam_tracker[gid][uid]
        timestamps.append(now)
        timestamps[:] = [t for t in timestamps if (now - t).total_seconds() <= window]

        if len(timestamps) >= max_msgs:
            timestamps.clear()
            await self._punish_spam(message)

    async def _punish_spam(self, message: discord.Message):
        member = message.author
        guild  = message.guild
        reason = "Auto-Mod: Spam detected"

        db.log_security_event(guild.id, "SPAM_DETECTED", member.id,
                              f"#{message.channel.name}", severity="medium")

        punishment = SPAM_CFG["punishment"]
        if punishment == "mute":
            duration = SPAM_CFG["mute_duration_minutes"]
            until    = datetime.utcnow() + timedelta(minutes=duration)
            try:
                await member.timeout(until, reason=reason)
            except:
                pass
            action_text = f"Muted for {duration} minutes"
        elif punishment == "kick":
            try:
                await member.kick(reason=reason)
            except:
                pass
            action_text = "Kicked"
        elif punishment == "ban":
            try:
                await member.ban(reason=reason)
            except:
                pass
            action_text = "Banned"
        else:
            action_text = "Warning issued"

        try:
            await message.channel.send(embed=discord.Embed(
                title="🛡️ Anti-Spam Triggered",
                description=f"{member.mention} was detected spamming.\n**Action:** {action_text}",
                color=WARNING
            ), delete_after=8)
        except:
            pass

        settings = db.get_guild_settings(guild.id)
        if settings and settings.get("mod_log_id"):
            ch = guild.get_channel(settings["mod_log_id"])
            if ch:
                embed = discord.Embed(
                    title="🛡️ Anti-Spam | Auto-Mod",
                    color=WARNING,
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
                embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                embed.add_field(name="Action", value=action_text, inline=True)
                embed.set_footer(text="TFF Bot • Security")
                await ch.send(embed=embed)

    # ── Anti-Raid: on_member_join ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not RAID_CFG["enabled"]:
            return

        gid = member.guild.id
        now = datetime.utcnow()
        window = RAID_CFG["join_window_seconds"]
        threshold = RAID_CFG["join_threshold"]

        joins = self._join_tracker[gid]
        joins.append(now)
        joins[:] = [t for t in joins if (now - t).total_seconds() <= window]

        # New account check
        account_age = (now - member.created_at.replace(tzinfo=None)).days
        min_age = RAID_CFG["new_account_age_days"]
        if account_age < min_age:
            db.log_security_event(gid, "NEW_ACCOUNT_JOIN", member.id,
                                  f"Account age: {account_age}d", severity="low")

        if len(joins) >= threshold and gid not in self._lockdown_guilds:
            self._lockdown_guilds.add(gid)
            await self._trigger_raid_lockdown(member.guild)

    async def _trigger_raid_lockdown(self, guild: discord.Guild):
        db.log_security_event(guild.id, "RAID_DETECTED", None, "Auto-lockdown triggered", severity="critical")
        db.upsert_guild_settings(guild.id, lockdown_active=1)

        for channel in guild.text_channels:
            try:
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = False
                await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="Anti-Raid Lockdown")
            except:
                pass

        settings = db.get_guild_settings(guild.id)
        alert_ch = None
        if settings and settings.get("alert_channel"):
            alert_ch = guild.get_channel(settings["alert_channel"])
        if not alert_ch:
            alert_ch = guild.system_channel

        if alert_ch:
            embed = discord.Embed(
                title="🚨 RAID DETECTED — SERVER LOCKED",
                description=(
                    "An unusual number of members joined in a short time.\n"
                    "The server has been **automatically locked down**.\n\n"
                    "Use `/raidmode off` to unlock the server."
                ),
                color=ERROR,
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="TFF Bot • Anti-Raid System")
            await alert_ch.send(embed=embed)

    # ── /raidmode ─────────────────────────────────────────────────────────────
    @app_commands.command(name="raidmode", description="Manually enable or disable raid lockdown.")
    @app_commands.describe(mode="on or off")
    @admin_only()
    async def raidmode(self, interaction: discord.Interaction, mode: str):
        await interaction.response.defer(ephemeral=True)
        mode = mode.lower()
        guild = interaction.guild

        if mode == "on":
            self._lockdown_guilds.add(guild.id)
            await self._trigger_raid_lockdown(guild)
            embed = discord.Embed(title="🔒 Raid Mode Enabled", description="Server is now in lockdown.", color=ERROR)
        elif mode == "off":
            self._lockdown_guilds.discard(guild.id)
            db.upsert_guild_settings(guild.id, lockdown_active=0)
            for channel in guild.text_channels:
                try:
                    overwrite = channel.overwrites_for(guild.default_role)
                    overwrite.send_messages = None
                    await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="Raid mode disabled")
                except:
                    pass
            embed = discord.Embed(title="🔓 Raid Mode Disabled", description="Server lockdown has been lifted.", color=SUCCESS)
        else:
            embed = discord.Embed(title="❌ Invalid", description="Use `on` or `off`.", color=ERROR)

        embed.set_footer(text="TFF Bot • Security")
        await interaction.followup.send(embed=embed)

    # ── /setupverification ────────────────────────────────────────────────────
    @app_commands.command(name="setupverification", description="Set up the member verification system.")
    @app_commands.describe(channel="Channel where users will verify")
    @admin_only()
    async def setupverification(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        verified_role = discord.utils.get(guild.roles, name=VERIFY_CFG["verified_role_name"])
        if not verified_role:
            verified_role = await guild.create_role(name=VERIFY_CFG["verified_role_name"], color=discord.Color.green())

        db.upsert_guild_settings(guild.id, verify_channel=channel.id, verified_role=verified_role.id)

        embed = discord.Embed(
            title="🛡️ Verification System",
            description=(
                "Welcome to **TFF Bot** verification!\n\n"
                "To gain access to the server, click the button below and complete the quick verification."
            ),
            color=PRIMARY
        )
        embed.set_footer(text="TFF Bot • Verification")

        view = VerifyView(self.bot, verified_role.id)
        await channel.send(embed=embed, view=view)

        await interaction.followup.send(embed=discord.Embed(
            title="✅ Verification Setup",
            description=f"Verification system configured in {channel.mention}.",
            color=SUCCESS
        ), ephemeral=True)

    # ── /securitystatus ───────────────────────────────────────────────────────
    @app_commands.command(name="securitystatus", description="View the current security status of the server.")
    @admin_only()
    async def securitystatus(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        events = db.get_security_events(interaction.guild.id, limit=5)
        settings = db.get_guild_settings(interaction.guild.id) or {}

        embed = discord.Embed(
            title=f"🛡️ Security Status — {interaction.guild.name}",
            color=PRIMARY,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Anti-Spam",   value="✅ Enabled" if SPAM_CFG["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Anti-Raid",   value="✅ Enabled" if RAID_CFG["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Verification",value="✅ Enabled" if VERIFY_CFG["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Lockdown",    value="🔒 Active" if settings.get("lockdown_active") else "🔓 Inactive", inline=True)

        if events:
            recent = "\n".join(
                f"`{e['event_type']}` — {e['logged_at'][:16]} [{e['severity'].upper()}]"
                for e in events
            )
            embed.add_field(name="Recent Security Events", value=recent, inline=False)
        else:
            embed.add_field(name="Recent Security Events", value="No events logged.", inline=False)

        embed.set_footer(text="TFF Bot • Security")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Cleanup Task ──────────────────────────────────────────────────────────
    @tasks.loop(minutes=5)
    async def cleanup_spam(self):
        now = datetime.utcnow()
        window = SPAM_CFG["time_window_seconds"]
        for gid in list(self._spam_tracker.keys()):
            for uid in list(self._spam_tracker[gid].keys()):
                self._spam_tracker[gid][uid] = [
                    t for t in self._spam_tracker[gid][uid]
                    if (now - t).total_seconds() <= window
                ]

    @cleanup_spam.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()


# ── Verification Button View ──────────────────────────────────────────────────

class VerifyView(discord.ui.View):
    def __init__(self, bot, verified_role_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.verified_role_id = verified_role_id

    @discord.ui.button(label="✅ Verify Me", style=discord.ButtonStyle.success, custom_id="verify_btn")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        guild  = interaction.guild
        code   = "".join(random.choices(string.ascii_uppercase + string.digits, k=VERIFY_CFG["captcha_length"]))
        expires = (datetime.utcnow() + timedelta(minutes=VERIFY_CFG["verification_timeout_minutes"])).strftime("%Y-%m-%d %H:%M:%S")
        db.create_verification(guild.id, member.id, code, expires)

        try:
            dm_embed = discord.Embed(
                title="🔐 TFF Bot — Verification Code",
                description=(
                    f"Your verification code for **{guild.name}** is:\n\n"
                    f"```{code}```\n"
                    f"Use `/verify code:{code}` in the server to complete verification.\n"
                    f"This code expires in **{VERIFY_CFG['verification_timeout_minutes']} minutes**."
                ),
                color=int(CONFIG["bot"]["color"])
            )
            await member.send(embed=dm_embed)
            await interaction.response.send_message(embed=discord.Embed(
                title="📬 Code Sent!",
                description="Check your DMs for your verification code, then use `/verify` in the server.",
                color=int(CONFIG["bot"]["success_color"])
            ), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ DMs Closed",
                description="I couldn't send you a DM. Please enable DMs from server members and try again.",
                color=int(CONFIG["bot"]["error_color"])
            ), ephemeral=True)


class VerifyCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="verify", description="Complete your server verification with your code.")
    @app_commands.describe(code="Your verification code received via DM")
    async def verify(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        guild  = interaction.guild
        member = interaction.user

        settings = db.get_guild_settings(guild.id)
        if not settings or not settings.get("verified_role"):
            return await interaction.followup.send(embed=discord.Embed(
                title="❌ Not Setup", description="Verification has not been configured for this server.", color=int(CONFIG["bot"]["error_color"])
            ), ephemeral=True)

        if db.verify_code(guild.id, member.id, code.upper()):
            role = guild.get_role(settings["verified_role"])
            if role:
                try:
                    await member.add_roles(role, reason="Verification completed")
                except:
                    pass
            db.log_security_event(guild.id, "USER_VERIFIED", member.id, "Verification successful", "low")
            await interaction.followup.send(embed=discord.Embed(
                title="✅ Verified!",
                description=f"You've been verified and granted access to **{guild.name}**!",
                color=int(CONFIG["bot"]["success_color"])
            ), ephemeral=True)
        else:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Invalid Code",
                description="That code is incorrect or has expired. Please request a new one.",
                color=int(CONFIG["bot"]["error_color"])
            ), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Security(bot))
    await bot.add_cog(VerifyCommand(bot))
