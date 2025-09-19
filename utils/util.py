from dis_commands import bot
import logging, colorlog, os

# (Logging, Data Directory, and Constants Setup)
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)s: %(message)s',
    log_colors={'DEBUG':'bold_cyan','INFO':'bold_green','WARNING':'bold_yellow','ERROR':'red','CRITICAL':'bold_red'}
))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# --- Discord Logic functions ---
async def find_guild_by_name(name):
    """Finds a guild by name (case-insensitive) and returns its ID."""
    for guild in bot.guilds:
        if guild.name.lower() == name.lower():
            logger.info(f"Found guild '{name}' (case-insensitive) with ID {guild.id}")
            return guild.id
    logger.warning(f"Guild with name '{name}' not found.")
    return None

async def fetch_channels_from_guild(guild_id):
    try:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            logger.error(f"Guild with ID {guild_id} not found.")
            return None
        available_channels = [
            {"name": channel.name, "id": channel.id}
            for channel in guild.text_channels
            if channel.permissions_for(guild.me).send_messages
        ]
        logger.info(f"Found {len(available_channels)} accessible channels in server '{guild.name}'.")
        return {"channels": available_channels, "guild_name": guild.name}
    except Exception as e:
        logger.error(f"An error occurred while fetching channels: {e}")
        return None