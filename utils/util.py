from dis_commands import bot
import logging, colorlog, os, discord, json, uuid, asyncio, shutil
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
CHUNK_SIZE = os.getenv("CHUNK_SIZE") # Default to 10MB if not set

# --- File Handling Helpers ---
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

# --- Upload Logic ---
async def upload_single_file(file_path, original_filename, server_id, channel_name, secure):
    """Handles the upload process for a single file using the unified chunker."""
    guild = bot.get_guild(int(server_id))
    if not guild: return logger.error(f"Upload failed: Guild {server_id} not found.")
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return logger.error(f'Upload failed: Channel "{channel_name}" not found.')

    try:
        # Use the unified helper for all processing and naming
        chunk_paths, chunk_basenames = _process_and_chunk_file(file_path, secure)

        metadata = {
            "original_filename": original_filename,
            "chunks": chunk_basenames,
            "encrypted": secure
        }
        metadata_filename = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}_metadata.json")
        metadata_content = json.dumps(metadata).encode()
        if secure: metadata_content = cipher.encrypt(metadata_content)
        with open(metadata_filename, 'wb') as f: f.write(metadata_content)

        await channel.send(file=discord.File(metadata_filename, filename=f"{original_filename}_metadata.json"))
        os.remove(metadata_filename)

        for chunk_path in chunk_paths:
            await channel.send(file=discord.File(chunk_path, filename=os.path.basename(chunk_path)))
            os.remove(chunk_path) # Clean up chunk as we go
            await asyncio.sleep(1.5)

        logger.info(f"Successfully uploaded '{original_filename}'.")
    except Exception as e:
        logger.error(f"An error occurred during upload for '{original_filename}': {e}")

async def upload_folder(metadata_obj, chunk_paths, server_id, channel_name):
    """Uploads a single metadata file, then all the chunks for a folder."""
    guild = bot.get_guild(int(server_id))
    if not guild:
        logger.error(f"Upload failed: Guild {server_id} not found.")
        return
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        logger.error(f'Upload failed: Channel "{channel_name}" not found.')
        return

    # 1. Prepare and Upload Metadata
    metadata_filename = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}_metadata.json")
    metadata_content = json.dumps(metadata_obj, indent=2).encode()
    if metadata_obj.get("encrypted", False): metadata_content = cipher.encrypt(metadata_content)
    with open(metadata_filename, 'wb') as f: f.write(metadata_content)

    try:
        logger.info(f"Uploading metadata for folder '{metadata_obj['folder_name']}'...")
        await channel.send(file=discord.File(metadata_filename, filename=f"{metadata_obj['folder_name']}_metadata.json"))
    finally:
        os.remove(metadata_filename)

    # 2. Upload All Chunks
    logger.info(f"Uploading {len(chunk_paths)} total chunks...")
    for i, chunk_path in enumerate(chunk_paths):
        try:
            logger.info(f"Uploading chunk {i+1}/{len(chunk_paths)}: {os.path.basename(chunk_path)}")
            await channel.send(file=discord.File(chunk_path, filename=os.path.basename(chunk_path).replace(' ', '_')))
            await asyncio.sleep(1.5)
        finally:
            if os.path.exists(chunk_path): os.remove(chunk_path)
    logger.info(f"Successfully uploaded folder '{metadata_obj['folder_name']}'.")

# --- Download Logic ---
async def download_from_discord(server_id, channel_name, requested_path):
    """Downloads a file or folder, with synchronized and robust error handling."""
    guild = bot.get_guild(int(server_id))
    if not guild: return logger.error(f"Download failed: Guild {server_id} not found.")
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return logger.error(f"Download failed: Channel '{channel_name}' not found.")

    root_object_name = requested_path.split('/')[0]
    metadata_filename_to_find = f"{root_object_name}_metadata.json"
    
    logger.info("Building file cache from channel history...")
    file_cache = {
        attachment.filename: message
        async for message in channel.history(limit=2000)
        for attachment in message.attachments
    }
    logger.info(f"Cache built with {len(file_cache)} files.")

    metadata_message = file_cache.get(metadata_filename_to_find)
    if not metadata_message: return logger.error(f"Metadata for '{root_object_name}' not found.")

    encrypted_metadata_content = await metadata_message.attachments[0].read()
    try:
        metadata = json.loads(cipher.decrypt(encrypted_metadata_content))
    except Exception:
        metadata = json.loads(encrypted_metadata_content)
    
    is_encrypted = metadata.get("encrypted", False)

    if metadata.get("upload_type") == "folder":
        path_parts = requested_path.split('/')
        if len(path_parts) > 1:
            logger.info(f"Request is for a specific file inside a folder: {requested_path}")
            current_item = {"children": metadata["tree"]}
            for part in path_parts:
                current_item = current_item.get("children", {}).get(part)
                if not current_item:
                    logger.error(f"Path '{requested_path}' not found in folder metadata.")
                    return None
            
            if current_item.get("type") == "file":
                reassembled_file_path = os.path.join(DATA_DIRECTORY, os.path.basename(requested_path))
                all_chunks_found = True
                with open(reassembled_file_path, 'wb') as f:
                    for chunk_filename in current_item["chunks"]:
                        if chunk_filename in file_cache:
                            f.write(await file_cache[chunk_filename].attachments[0].read())
                        else:
                            all_chunks_found = False
                            break
                if not all_chunks_found: return None
                if is_encrypted:
                    with open(reassembled_file_path, 'rb') as f: data = f.read()
                    with open(reassembled_file_path, 'wb') as f: f.write(cipher.decrypt(data))
                return reassembled_file_path
            else:
                return None
        else:
            logger.info(f"Request is for the entire folder: {metadata['folder_name']}. Preparing ZIP.")
            base_download_path = os.path.join(DATA_DIRECTORY, metadata['folder_name'])
            if os.path.exists(base_download_path): shutil.rmtree(base_download_path)
            os.makedirs(base_download_path)

            await _build_folder_from_tree(channel, metadata["tree"], base_download_path, file_cache, is_encrypted)
            
            zip_path = os.path.join(DATA_DIRECTORY, f"{metadata['folder_name']}.zip")
            shutil.make_archive(base_name=zip_path.replace('.zip', ''), format='zip', root_dir=base_download_path)
            shutil.rmtree(base_download_path)
            logger.info(f"Folder successfully zipped to {zip_path}")
            return zip_path
    else:
        logger.info(f"Request is for a single file: {metadata['original_filename']}")
        reassembled_file_path = os.path.join(DATA_DIRECTORY, metadata["original_filename"])
        all_chunks_found = True
        with open(reassembled_file_path, 'wb') as f:
            for chunk_filename in metadata["chunks"]:
                if chunk_filename in file_cache:
                    f.write(await file_cache[chunk_filename].attachments[0].read())
                else:
                    logger.error(f"FATAL: Chunk '{chunk_filename}' not found for file '{metadata['original_filename']}'")
                    all_chunks_found = False
                    break
        
        if not all_chunks_found:
            if os.path.exists(reassembled_file_path): os.remove(reassembled_file_path)
            return None

        if is_encrypted:
            try:
                with open(reassembled_file_path, 'rb') as f: data = f.read()
                with open(reassembled_file_path, 'wb') as f: f.write(cipher.decrypt(data))
            except Exception as e:
                logger.error(f"Decryption failed for '{metadata['original_filename']}': {e}")
                if os.path.exists(reassembled_file_path): os.remove(reassembled_file_path)
                return None
        return reassembled_file_path

async def _build_folder_from_tree(channel, metadata_tree, base_download_path, file_cache, is_encrypted):
    """Recursively traverses the metadata tree and downloads files."""
    for name, item in metadata_tree.items():
        current_path = os.path.join(base_download_path, name)
        if item["type"] == "directory":
            os.makedirs(current_path, exist_ok=True)
            await _build_folder_from_tree(channel, item["children"], current_path, file_cache, is_encrypted)
        elif item["type"] == "file":
            logger.info(f"Reassembling file: {current_path}")
            
            all_chunks_found = True
            with open(current_path, 'wb') as reassembled_file:
                for chunk_filename in item["chunks"]:
                    if chunk_filename in file_cache:
                        chunk_message = file_cache[chunk_filename]
                        chunk_content = await chunk_message.attachments[0].read()
                        reassembled_file.write(chunk_content)
                    else:
                        logger.error(f"FATAL: Chunk '{chunk_filename}' for file '{name}' not found in cache!")
                        all_chunks_found = False
                        break
            
            if all_chunks_found and is_encrypted:
                try:
                    with open(current_path, 'rb') as f: encrypted_data = f.read()
                    decrypted_data = cipher.decrypt(encrypted_data)
                    with open(current_path, 'wb') as f: f.write(decrypted_data)
                except Exception as e:
                    logger.error(f"Decryption failed for '{name}': {e}")
            elif not all_chunks_found:
                 if os.path.exists(current_path):
                     os.remove(current_path)