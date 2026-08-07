import asyncio
import logging

import discord
from discord.ext import commands

import config
import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("lebondeal-bot")

intents = discord.Intents.default()
intents.message_content = False  # non nécessaire, tout passe par les commandes slash

bot = commands.Bot(command_prefix="!", intents=intents)

EXTENSIONS = ["cogs.filters", "cogs.settings", "cogs.dashboard"]


@bot.event
async def on_ready():
    log.info("Connecté en tant que %s (%s)", bot.user, bot.user.id)
    scheduler.init(bot)
    await scheduler.sync()
    log.info("Scheduler synchronisé.")


async def setup_hook():
    for ext in EXTENSIONS:
        await bot.load_extension(ext)
    if config.GUILD_ID:
        guild = discord.Object(id=config.GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        log.info("Commandes synchronisées sur la guild %s (instantané).", config.GUILD_ID)
    else:
        await bot.tree.sync()
        log.info("Commandes synchronisées globalement (peut prendre jusqu'à 1h à apparaître).")


bot.setup_hook = setup_hook


async def main():
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
