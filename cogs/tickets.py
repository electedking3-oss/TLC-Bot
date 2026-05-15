import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime
from typing import Optional
import database as db
import io

with open("config.json") as f:
    CONFIG = json.load(f)

TKT_CFG = CONFIG["tickets"]
SUCCESS = int(CONFIG["bot"]["success_color"])
ERROR   = int(CONFIG["bot"]["error_color"])
PRIMARY = int(CONFIG["bot"]["color"])
WARNING = int(CONFIG["bot"]["warning_color"])


def admin_only():
    async def predicate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied", description="Administrator permission required.", color=ERROR
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await TicketSystem.create_ticket_for(interaction)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
    async def close_ticket_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = db.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
        await TicketSystem.do_close_ticket(interaction, ticket)

    @discord.ui.button(label="📋 Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket_btn")
    async def claim_ticket_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Staff only.", ephemeral=True)
        ticket = db.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            return
        db.claim_ticket(interaction.channel.id, interaction.user.id)
        await interaction.response.send_message(embed=discord.Embed(
            title="📋 Ticket Claimed",
            description=f"{interaction.user.mention} is now handling this ticket.",
            color=SUCCESS
        ))

    @discord.ui.button(label="📄 Transcript", style=discord.ButtonStyle.secondary, custom_id="transcript_btn")
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Staff only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        transcript = await TicketSystem.generate_transcript(interaction.channel)
        buf = io.BytesIO(transcript.encode("utf-8"))
        file = discord.File(buf, filename=f"transcript-{interaction.channel.name}.txt")
        await interaction.followup.send("📄 Transcript generated:", file=file, ephemeral=True)


class TicketSystem:

    @staticmethod
    async def create_ticket_for(interaction: discord.Interaction, subject: str = None):
        guild  = interaction.guild
        member = interaction.user

        open_tickets = db.get_user_open_tickets(guild.id, member.id)
        if len(open_tickets) >= TKT_CFG["max_tickets_per_user"]:
            return await interaction.response.send_message(embed=discord.Embed(
                title="❌ Ticket Limit",
                description=f"You already have an open ticket. Please close it before opening a new one.",
                color=ERROR
            ), ephemeral=True)

        settings = db.get_guild_settings(guild.id)
        category = None
        if settings and settings.get("ticket_category"):
            category = guild.get_channel(settings["ticket_category"])
        if not category:
            category = discord.utils.get(guild.categories, name=TKT_CFG["category_name"])

        ticket_num = db.get_next_ticket_number(guild.id)
        channel_name = f"{TKT_CFG['ticket_prefix']}-{str(ticket_num).zfill(4)}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        if settings and settings.get("support_role"):
            support_role = guild.get_role(settings["support_role"])
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Ticket #{ticket_num} | {member} | {subject or 'No subject'}"
        )

        db.create_ticket(guild.id, ticket_channel.id, member.id, ticket_num, subject)

        embed = discord.Embed(
            title=f"🎫 Ticket #{str(ticket_num).zfill(4)}",
            description=(
                f"Welcome {member.mention}!\n\n"
                f"Please describe your issue and a staff member will assist you shortly.\n\n"
                f"{'**Subject:** ' + subject if subject else ''}"
            ),
            color=PRIMARY,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="TFF Bot • Ticket System")
        if settings and settings.get("support_role"):
            support_role = guild.get_role(settings["support_role"])
            if support_role and TKT_CFG["ping_support_on_open"]:
                await ticket_channel.send(support_role.mention, embed=embed, view=TicketControlView())
            else:
                await ticket_channel.send(embed=embed, view=TicketControlView())
        else:
            await ticket_channel.send(embed=embed, view=TicketControlView())

        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Ticket Created",
            description=f"Your ticket has been opened: {ticket_channel.mention}",
            color=SUCCESS
        ), ephemeral=True)

    @staticmethod
    async def do_close_ticket(interaction: discord.Interaction, ticket: dict):
        await interaction.response.defer()
        channel = interaction.channel
        guild   = interaction.guild

        transcript = await TicketSystem.generate_transcript(channel)
        db.close_ticket(channel.id, transcript)

        settings = db.get_guild_settings(guild.id)
        if settings and settings.get("transcript_channel"):
            tc = guild.get_channel(settings["transcript_channel"])
            if tc:
                buf = io.BytesIO(transcript.encode("utf-8"))
                f   = discord.File(buf, filename=f"transcript-{channel.name}.txt")
                opener = guild.get_member(ticket["user_id"])
                t_embed = discord.Embed(
                    title=f"📄 Ticket #{str(ticket['ticket_number']).zfill(4)} Closed",
                    description=f"**Opened by:** {opener.mention if opener else ticket['user_id']}\n**Closed by:** {interaction.user.mention}",
                    color=WARNING,
                    timestamp=datetime.utcnow()
                )
                t_embed.set_footer(text="TFF Bot • Ticket Transcripts")
                await tc.send(embed=t_embed, file=f)

        close_embed = discord.Embed(
            title="🔒 Ticket Closing",
            description="This ticket will be deleted in 5 seconds.",
            color=ERROR
        )
        await channel.send(embed=close_embed)
        await discord.utils.sleep_until(datetime.utcnow().__class__.utcnow())
        import asyncio
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except:
            pass

    @staticmethod
    async def generate_transcript(channel: discord.TextChannel) -> str:
        lines = [f"=== TICKET TRANSCRIPT: #{channel.name} ===", f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}", ""]
        async for message in channel.history(limit=500, oldest_first=True):
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content   = message.content or "[embed/attachment]"
            lines.append(f"[{timestamp}] {message.author} ({message.author.id}): {content}")
        return "\n".join(lines)


class Tickets(commands.Cog):
    """Advanced Ticket System for TLC Bot."""

    def __init__(self, bot):
        self.bot = bot

    # ── /setuptickets ─────────────────────────────────────────────────────────
    @app_commands.command(name="setuptickets", description="Set up the ticket system with a panel.")
    @app_commands.describe(channel="Channel to send the ticket panel to")
    @admin_only()
    async def setuptickets(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        category = discord.utils.get(guild.categories, name=TKT_CFG["category_name"])
        if not category:
            category = await guild.create_category(TKT_CFG["category_name"])

        db.upsert_guild_settings(guild.id, ticket_category=category.id)

        embed = discord.Embed(
            title="🎫 Support Tickets",
            description=(
                "Need help? Click the button below to open a support ticket.\n\n"
                "A staff member will assist you as soon as possible.\n"
                f"**Max tickets per user:** {TKT_CFG['max_tickets_per_user']}"
            ),
            color=PRIMARY,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="TFF Bot • Ticket System")
        await channel.send(embed=embed, view=TicketView())

        await interaction.followup.send(embed=discord.Embed(
            title="✅ Tickets Setup",
            description=f"Ticket panel sent to {channel.mention}.\nTickets category: `{category.name}`",
            color=SUCCESS
        ), ephemeral=True)

    # ── /newticket ────────────────────────────────────────────────────────────
    @app_commands.command(name="newticket", description="Open a new support ticket.")
    @app_commands.describe(subject="Brief description of your issue")
    async def newticket(self, interaction: discord.Interaction, subject: Optional[str] = None):
        await TicketSystem.create_ticket_for(interaction, subject)

    # ── /closeticket ──────────────────────────────────────────────────────────
    @app_commands.command(name="closeticket", description="Close this ticket.")
    @admin_only()
    async def closeticket(self, interaction: discord.Interaction):
        ticket = db.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message(embed=discord.Embed(
                title="❌ Not a Ticket", description="This command can only be used in a ticket channel.", color=ERROR
            ), ephemeral=True)
        await TicketSystem.do_close_ticket(interaction, ticket)

    # ── /adduser ──────────────────────────────────────────────────────────────
    @app_commands.command(name="adduser", description="Add a user to this ticket.")
    @app_commands.describe(member="Member to add")
    @admin_only()
    async def adduser(self, interaction: discord.Interaction, member: discord.Member):
        ticket = db.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
        await interaction.response.send_message(embed=discord.Embed(
            title="➕ User Added",
            description=f"{member.mention} has been added to this ticket.",
            color=SUCCESS
        ))

    # ── /removeuser ───────────────────────────────────────────────────────────
    @app_commands.command(name="removeuser", description="Remove a user from this ticket.")
    @app_commands.describe(member="Member to remove")
    @admin_only()
    async def removeuser(self, interaction: discord.Interaction, member: discord.Member):
        ticket = db.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(embed=discord.Embed(
            title="➖ User Removed",
            description=f"{member.mention} has been removed from this ticket.",
            color=WARNING
        ))

    # ── /settranscriptchannel ─────────────────────────────────────────────────
    @app_commands.command(name="settranscriptchannel", description="Set the channel for ticket transcripts.")
    @app_commands.describe(channel="Transcript channel")
    @admin_only()
    async def settranscriptchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.upsert_guild_settings(interaction.guild.id, transcript_channel=channel.id)
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Transcript Channel Set",
            description=f"Ticket transcripts will be sent to {channel.mention}.",
            color=SUCCESS
        ), ephemeral=True)

    # ── /setsupportrole ───────────────────────────────────────────────────────
    @app_commands.command(name="setsupportrole", description="Set the support staff role for tickets.")
    @app_commands.describe(role="The support role")
    @admin_only()
    async def setsupportrole(self, interaction: discord.Interaction, role: discord.Role):
        db.upsert_guild_settings(interaction.guild.id, support_role=role.id)
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Support Role Set",
            description=f"{role.mention} will be pinged and added to all new tickets.",
            color=SUCCESS
        ), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
