import discord
from discord.ext import commands, tasks
import asyncio
import logging
import json
import os
import sys
from datetime import datetime
from database import init_database
from dotenv import load_dotenv
load_dotenv()

# ── Load Config ───────────────────────────────────────────────────────────────
with open("config.json", "r") as f:
    CONFIG = json.load(f)

# ── Logging Setup ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(f"logs/tlcbot_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TLCBot")

# ── Bot Setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

bot.config = CONFIG
bot.owner_ids_list = [int(uid) for uid in CONFIG["owners"]]

# ── Cogs to Load ──────────────────────────────────────────────────────────────
COGS = [
    "cogs.moderation",
    "cogs.security",
    "cogs.logging_cog",
    "cogs.tickets",
    "cogs.admin",
    "cogs.monitoring",
    "cogs.welcome",
]

# ── Bot Events ────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    logger.info(f"✅ {bot.user} is online and ready!")
    logger.info(f"   Guilds  : {len(bot.guilds)}")
    logger.info(f"   Commands: {len(bot.tree.get_commands())}")

    status_map = {
        "playing":   discord.ActivityType.playing,
        "watching":  discord.ActivityType.watching,
        "listening": discord.ActivityType.listening,
        "competing": discord.ActivityType.competing,
    }
    activity_type = status_map.get(CONFIG["bot"]["status_type"], discord.ActivityType.watching)
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=activity_type, name=CONFIG["bot"]["status"])
    )


@bot.event
async def on_guild_join(guild: discord.Guild):
    logger.info(f"Joined guild: {guild.name} ({guild.id})")


@bot.event
async def on_command_error(ctx, error):
    logger.error(f"Command error: {error}")


# ── Owner-Only Check ──────────────────────────────────────────────────────────
def is_bot_owner():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id not in bot.owner_ids_list:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="This command is reserved for the **Bot Owner** only.",
                    color=int(CONFIG["bot"]["error_color"])
                ),
                ephemeral=True
            )
            return False
        return True
    return discord.app_commands.check(predicate)


# ── Admin Permission Check ────────────────────────────────────────────────────
def is_server_admin():
    async def predicate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="You need the **Administrator** permission to use this command.",
                    color=int(CONFIG["bot"]["error_color"])
                ),
                ephemeral=True
            )
            return False
        return True
    return discord.app_commands.check(predicate)


bot.is_bot_owner = is_bot_owner
bot.is_server_admin = is_server_admin


# ── Startup ───────────────────────────────────────────────────────────────────
async def main():
    init_database()
    logger.info("Database initialized.")

    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                logger.info(f"  ✅ Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"  ❌ Failed to load {cog}: {e}")

        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logger.critical("DISCORD_TOKEN not found in environment. Set it with: export DISCORD_TOKEN=your_token")
            sys.exit(1)

        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
