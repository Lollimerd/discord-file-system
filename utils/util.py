from dis_commands import bot
import logging, colorlog, os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

# (Logging, Data Directory, and Constants Setup)
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)s: %(message)s',
    log_colors={'DEBUG':'bold_cyan','INFO':'bold_green','WARNING':'bold_yellow','ERROR':'red','CRITICAL':'bold_red'}
))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.DEBUG)
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
    
# --- File Handling and Discord Upload/Download ---
ENCRYPTION_KEY = os.getenv("enc_key").encode()
cipher = Fernet(ENCRYPTION_KEY)
CHUNK_SIZE = 10 * 1024 * 1024 # Default to 10MB if not set
DATA_DIRECTORY = 'Data'
if not os.path.exists(DATA_DIRECTORY): os.makedirs(DATA_DIRECTORY)

def _process_and_chunk_file(source_path, secure):
    """
    Handles in-place encryption and consistent chunking for any given file.
    All chunks, including for single-part files, will contain '_part_'.
    Returns a tuple of (list of full chunk paths, list of chunk basenames).
    """
    if secure:
        with open(source_path, 'rb') as f: data = f.read()
        with open(source_path, 'wb') as f: f.write(cipher.encrypt(data))

    chunk_paths = []
    chunk_basenames = []
    base, ext = os.path.splitext(os.path.basename(source_path))

    if os.path.getsize(source_path) > CHUNK_SIZE:
        with open(source_path, 'rb') as f:
            for i, chunk_data in enumerate(iter(lambda: f.read(CHUNK_SIZE), b'')):
                chunk_path = os.path.join(DATA_DIRECTORY, f"{base}_part_{i}{ext}")
                with open(chunk_path, 'wb') as cf: cf.write(chunk_data)
                chunk_paths.append(chunk_path)
                chunk_basenames.append(os.path.basename(chunk_path))
    else:
        # For single-part files, rename them to follow the chunking convention
        chunk_path = os.path.join(DATA_DIRECTORY, f"{base}_part_0{ext}")
        os.rename(source_path, chunk_path)
        chunk_paths.append(chunk_path)
        chunk_basenames.append(os.path.basename(chunk_path))

    # Clean up the original source file if it was chunked into multiple parts
    if os.path.exists(source_path):
        os.remove(source_path)

    return chunk_paths, chunk_basenames