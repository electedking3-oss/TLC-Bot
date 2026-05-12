import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime
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


def owner_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id not in [int(uid) for uid in CONFIG["owners"]]:
            await interaction.response.send_message(embed=discord.Embed(
                title="❌ Access Denied",
                description="This command is **Bot Owner only**.",
                color=ERROR
            ), ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


class Admin(commands.Cog):
    """Server admin tools — nicknames, emojis, channels, embeds."""

    def __init__(self, bot):
        self.bot = bot

    # ══════════════════════════════════════════════════════════════════════════
    #  NICKNAME COMMANDS
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="resetnicknames", description="Reset ALL member nicknames at once.")
    @admin_only()
    async def resetnicknames(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild   = interaction.guild
        success = 0
        failed  = 0

        progress_embed = discord.Embed(
            title="⚙️ Resetting Nicknames...",
            description=f"Processing {len(guild.members)} members. Please wait...",
            color=WARNING
        )
        await interaction.followup.send(embed=progress_embed, ephemeral=True)

        for member in guild.members:
            if member.nick and not member.bot:
                try:
                    await member.edit(nick=None, reason=f"Nicknames reset by {interaction.user}")
                    success += 1
                    await asyncio.sleep(0.3)  # Respect rate limits
                except discord.Forbidden:
                    failed += 1
                except discord.HTTPException:
                    failed += 1

        embed = discord.Embed(
            title="✅ Nicknames Reset",
            color=SUCCESS,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="✅ Reset",   value=str(success), inline=True)
        embed.add_field(name="❌ Failed",  value=str(failed),  inline=True)
        embed.add_field(name="By",         value=str(interaction.user), inline=True)
        embed.set_footer(text="TFF Bot • Admin Tools")
        await interaction.edit_original_response(embed=embed)

    @app_commands.command(name="setnickname", description="Set a specific member's nickname.")
    @app_commands.describe(member="Member to rename", nickname="New nickname (leave empty to reset)")
    @admin_only()
    async def setnickname(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        await interaction.response.defer(ephemeral=True)
        old_nick = member.nick or member.name
        await member.edit(nick=nickname, reason=f"Set by {interaction.user}")
        embed = discord.Embed(
            title="✏️ Nickname Updated",
            color=SUCCESS,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Member", value=member.mention, inline=True)
        embed.add_field(name="Before", value=old_nick, inline=True)
        embed.add_field(name="After",  value=nickname or "*Reset*", inline=True)
        embed.set_footer(text="TFF Bot • Admin Tools")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  EMOJI COMMANDS
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="addemoji", description="Add an emoji to the server from a URL.")
    @app_commands.describe(name="Emoji name", url="Direct image URL for the emoji")
    @admin_only()
    async def addemoji(self, interaction: discord.Interaction, name: str, url: str):
        await interaction.response.defer(ephemeral=True)
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(embed=discord.Embed(
                            title="❌ Failed", description="Could not fetch the image from that URL.", color=ERROR
                        ), ephemeral=True)
                    image_data = await resp.read()

            emoji = await interaction.guild.create_custom_emoji(name=name, image=image_data, reason=f"Added by {interaction.user}")
            await interaction.followup.send(embed=discord.Embed(
                title="✅ Emoji Added",
                description=f"Added {emoji} :`{emoji.name}:`",
                color=SUCCESS
            ), ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Error", description=f"Failed to add emoji: {e}", color=ERROR
            ), ephemeral=True)

    @app_commands.command(name="deleteemoji", description="Delete a specific emoji from the server.")
    @app_commands.describe(emoji_name="Name of the emoji to delete")
    @admin_only()
    async def deleteemoji(self, interaction: discord.Interaction, emoji_name: str):
        await interaction.response.defer(ephemeral=True)
        emoji = discord.utils.get(interaction.guild.emojis, name=emoji_name)
        if not emoji:
            return await interaction.followup.send(embed=discord.Embed(
                title="❌ Not Found", description=f"No emoji named `{emoji_name}` found.", color=ERROR
            ), ephemeral=True)

        await emoji.delete(reason=f"Deleted by {interaction.user}")
        await interaction.followup.send(embed=discord.Embed(
            title="🗑️ Emoji Deleted",
            description=f"Deleted emoji `:{emoji_name}:`",
            color=SUCCESS
        ), ephemeral=True)

    @app_commands.command(name="clearallemojis", description="⚠️ Delete ALL custom emojis from the server.")
    @admin_only()
    async def clearallemojis(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        emojis  = interaction.guild.emojis
        if not emojis:
            return await interaction.followup.send(embed=discord.Embed(
                title="ℹ️ No Emojis", description="This server has no custom emojis.", color=PRIMARY
            ), ephemeral=True)

        confirm_embed = discord.Embed(
            title="⚠️ Confirm Deletion",
            description=f"This will delete **{len(emojis)} emojis**. Confirm within 30s by clicking below.",
            color=WARNING
        )
        view = ConfirmView(interaction.user)
        msg  = await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            return await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Cancelled", description="Emoji deletion cancelled.", color=ERROR
            ), view=None)

        deleted = 0
        for emoji in emojis:
            try:
                await emoji.delete(reason=f"All emojis cleared by {interaction.user}")
                deleted += 1
                await asyncio.sleep(0.3)
            except:
                pass

        await interaction.edit_original_response(embed=discord.Embed(
            title="🗑️ All Emojis Deleted",
            description=f"Successfully deleted **{deleted}** emojis.",
            color=SUCCESS
        ), view=None)

    @app_commands.command(name="listemojis", description="List all custom emojis in the server.")
    @admin_only()
    async def listemojis(self, interaction: discord.Interaction):
        emojis = interaction.guild.emojis
        if not emojis:
            return await interaction.response.send_message(embed=discord.Embed(
                title="ℹ️ No Emojis", description="No custom emojis found.", color=PRIMARY
            ), ephemeral=True)

        embed = discord.Embed(
            title=f"😀 Custom Emojis ({len(emojis)})",
            color=PRIMARY,
            timestamp=datetime.utcnow()
        )
        chunks = [emojis[i:i+20] for i in range(0, len(emojis), 20)]
        for i, chunk in enumerate(chunks[:3]):
            embed.add_field(
                name=f"Emojis {i*20+1}–{i*20+len(chunk)}",
                value=" ".join(str(e) for e in chunk),
                inline=False
            )
        embed.set_footer(text="TFF Bot • Admin Tools")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  CHANNEL COMMANDS
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="createchannel", description="Create a new text or voice channel.")
    @app_commands.describe(name="Channel name", type="text or voice", category="Optional category name")
    @admin_only()
    async def createchannel(self, interaction: discord.Interaction,
                             name: str,
                             type: str = "text",
                             category: str = None):
        await interaction.response.defer(ephemeral=True)
        guild    = interaction.guild
        cat_obj  = None
        if category:
            cat_obj = discord.utils.get(guild.categories, name=category)

        if type.lower() == "voice":
            ch = await guild.create_voice_channel(name, category=cat_obj, reason=f"Created by {interaction.user}")
        else:
            ch = await guild.create_text_channel(name, category=cat_obj, reason=f"Created by {interaction.user}")

        embed = discord.Embed(
            title="✅ Channel Created",
            description=f"Created {ch.mention} ({type.lower()} channel).",
            color=SUCCESS,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="TFF Bot • Admin Tools")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="deletechannel", description="Delete a channel.")
    @app_commands.describe(channel="Channel to delete", reason="Reason")
    @admin_only()
    async def deletechannel(self, interaction: discord.Interaction,
                             channel: discord.TextChannel,
                             reason: str = "Deleted by admin"):
        await interaction.response.defer(ephemeral=True)
        name = channel.name
        await channel.delete(reason=reason)
        await interaction.followup.send(embed=discord.Embed(
            title="🗑️ Channel Deleted",
            description=f"Channel `#{name}` has been deleted.",
            color=SUCCESS
        ), ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  DEADLINE CHANNEL
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="createdeadlinechannel", description="Create a deadline channel visible to two roles with an automated message.")
    @app_commands.describe(
        role1="First role",
        role2="Second role",
        channel_name="Name for the new channel",
        task="Task or project name",
        deadline="Deadline (e.g. June 15, 2025 at 5PM)"
    )
    @admin_only()
    async def createdeadlinechannel(self, interaction: discord.Interaction,
                                     role1: discord.Role,
                                     role2: discord.Role,
                                     channel_name: str,
                                     task: str,
                                     deadline: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
            role1:              discord.PermissionOverwrite(read_messages=True, send_messages=True),
            role2:              discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
            topic=f"Deadline channel for {task} | Due: {deadline}",
            reason=f"Deadline channel created by {interaction.user}"
        )

        template = CONFIG["deadline_channel"]["default_message"]
        message  = (template
                    .replace("{role1}",    role1.mention)
                    .replace("{role2}",    role2.mention)
                    .replace("{task}",     task)
                    .replace("{deadline}", deadline))

        deadline_embed = discord.Embed(
            title=f"⏰ Deadline: {task}",
            description=message,
            color=WARNING,
            timestamp=datetime.utcnow()
        )
        deadline_embed.add_field(name="📅 Deadline",  value=deadline,        inline=True)
        deadline_embed.add_field(name="👥 Role 1",    value=role1.mention,   inline=True)
        deadline_embed.add_field(name="👥 Role 2",    value=role2.mention,   inline=True)
        deadline_embed.add_field(name="📝 Task",      value=task,            inline=False)
        deadline_embed.set_footer(text="TFF Bot • Deadline System")

        msg = await channel.send(f"{role1.mention} {role2.mention}", embed=deadline_embed)
        db.add_deadline_channel(guild.id, channel.id, role1.id, role2.id, task, deadline)

        await interaction.followup.send(embed=discord.Embed(
            title="✅ Deadline Channel Created",
            description=f"Channel {channel.mention} created for **{task}**.\nDeadline: **{deadline}**",
            color=SUCCESS
        ), ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  /EMBED COMMAND
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="embed", description="Create and send a custom embed message.")
    @app_commands.describe(
        channel="Channel to send the embed to",
        title="Embed title",
        description="Embed description/body text",
        color="Hex color code (e.g. #3498DB)",
        image="Image URL (optional)",
        thumbnail="Thumbnail URL (optional)",
        footer="Footer text (optional)",
        author="Author name (optional)"
    )
    @admin_only()
    async def embed_cmd(self, interaction: discord.Interaction,
                        channel: discord.TextChannel,
                        title: str,
                        description: str,
                        color: str = None,
                        image: str = None,
                        thumbnail: str = None,
                        footer: str = None,
                        author: str = None):
        await interaction.response.defer(ephemeral=True)

        try:
            embed_color = int(color.strip("#"), 16) if color else PRIMARY
        except:
            embed_color = PRIMARY

        embed = discord.Embed(
            title=title,
            description=description,
            color=embed_color,
            timestamp=datetime.utcnow()
        )
        if image:
            embed.set_image(url=image)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if footer:
            embed.set_footer(text=footer)
        else:
            embed.set_footer(text="TFF Bot")
        if author:
            embed.set_author(name=author)

        await channel.send(embed=embed)
        await interaction.followup.send(embed=discord.Embed(
            title="✅ Embed Sent",
            description=f"Your embed has been sent to {channel.mention}.",
            color=SUCCESS
        ), ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    #  BOT OWNER ONLY COMMANDS
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="botstatus", description="[Owner] Change the bot's status/activity.")
    @app_commands.describe(status="New status message", type="playing/watching/listening/competing")
    @owner_only()
    async def botstatus(self, interaction: discord.Interaction, status: str, type: str = "watching"):
        type_map = {
            "playing":   discord.ActivityType.playing,
            "watching":  discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
        }
        activity_type = type_map.get(type.lower(), discord.ActivityType.watching)
        await self.bot.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(type=activity_type, name=status)
        )
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Status Updated",
            description=f"Bot status set to: **{type.title()} {status}**",
            color=SUCCESS
        ), ephemeral=True)

    @app_commands.command(name="guilds", description="[Owner] List all servers the bot is in.")
    @owner_only()
    async def guilds(self, interaction: discord.Interaction):
        guilds = self.bot.guilds
        embed  = discord.Embed(
            title=f"🌐 Active Servers ({len(guilds)})",
            color=PRIMARY,
            timestamp=datetime.utcnow()
        )
        for guild in guilds[:20]:
            embed.add_field(name=guild.name, value=f"ID: `{guild.id}` | Members: `{guild.member_count}`", inline=False)
        embed.set_footer(text="TFF Bot • Owner Panel")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="synccommands", description="[Owner] Force sync slash commands globally.")
    @owner_only()
    async def synccommands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        synced = await self.bot.tree.sync()
        await interaction.followup.send(embed=discord.Embed(
            title="✅ Commands Synced",
            description=f"Synced **{len(synced)}** commands globally.",
            color=SUCCESS
        ), ephemeral=True)

    @app_commands.command(name="announce", description="[Owner] Send a global announcement to all server system channels.")
    @app_commands.describe(message="The announcement message")
    @owner_only()
    async def announce(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        sent = 0
        embed = discord.Embed(
            title="📢 Announcement from TFF Bot",
            description=message,
            color=PRIMARY,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="TFF Bot • Global Announcement")
        for guild in self.bot.guilds:
            if guild.system_channel:
                try:
                    await guild.system_channel.send(embed=embed)
                    sent += 1
                except:
                    pass
        await interaction.followup.send(embed=discord.Embed(
            title="✅ Announced",
            description=f"Sent announcement to **{sent}/{len(self.bot.guilds)}** servers.",
            color=SUCCESS
        ), ephemeral=True)


# ── Confirm View ──────────────────────────────────────────────────────────────

class ConfirmView(discord.ui.View):
    def __init__(self, author: discord.User):
        super().__init__(timeout=30)
        self.author    = author
        self.confirmed = False

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("Not your action.", ephemeral=True)
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("Not your action.", ephemeral=True)
        self.stop()
        await interaction.response.defer()


async def setup(bot):
    await bot.add_cog(Admin(bot))
