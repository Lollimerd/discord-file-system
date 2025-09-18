# app.py

from flask import Flask, request, render_template, send_file, redirect, url_for, flash
import discord, os, threading, logging, json, asyncio, colorlog, uuid, zipfile, io
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from dis_commands import *

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24) 

TOKEN = os.getenv("bot_token")
ENCRYPTION_KEY = os.getenv("enc_key").encode()
cipher = Fernet(ENCRYPTION_KEY)

# (Logging, Data Directory, and Constants remain the same)
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)s: %(message)s',
    log_colors={'DEBUG':'bold_cyan','INFO':'bold_green','WARNING':'bold_yellow','ERROR':'red','CRITICAL':'bold_red'}
))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIRECTORY = 'Data'
if not os.path.exists(DATA_DIRECTORY): os.makedirs(DATA_DIRECTORY)
CHUNK_SIZE = 11 * 1024 * 1024

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/select_server', methods=['POST'])
def select_server():
    server_id = request.form.get('server_id')
    if not server_id or not server_id.isdigit():
        flash("Invalid Server ID format. Please enter numbers only.")
        return redirect(url_for('index'))

    future = asyncio.run_coroutine_threadsafe(is_guild_available(server_id), bot.loop)
    guild_is_valid = future.result()

    if guild_is_valid:
        return redirect(url_for('server_page', server_id=server_id))
    else:
        flash(f"Could not access Server ID {server_id}. Please check the ID and ensure the bot is a member.")
        return redirect(url_for('index'))

## ## THIS IS THE MAIN BACKEND CHANGE ## ##
@app.route('/server/<server_id>')
def server_page(server_id):
    # Fetch server name and channel list from the bot
    future = asyncio.run_coroutine_threadsafe(fetch_channels_from_guild(server_id), bot.loop)
    server_data = future.result()

    if server_data:
        return render_template(
            'main.html', 
            server_id=server_id, 
            guild_name=server_data['guild_name'], 
            channels=server_data['channels']
        )
    else:
        # Handle case where server becomes inaccessible
        flash(f"Could not retrieve data for Server ID {server_id}.")
        return redirect(url_for('index'))

# --- (Discord Logic functions remain the same) ---
async def is_guild_available(guild_id):
    try:
        guild = bot.get_guild(int(guild_id))
        return guild is not None
    except:
        return False

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
    
@app.route('/upload', methods=['POST'])
def upload_file():
    server_id = request.form.get('server_id')
    channel_name = request.form.get('channel')
    secure_upload = request.form.get('encrypt') == 'true'
    files = request.files.getlist('files[]')

    if not all([server_id, channel_name, files]):
        return 'Missing form data', 400

    # ## We now call a single task for the entire batch of files ##
    asyncio.run_coroutine_threadsafe(
        upload_folder_to_discord(files, server_id, channel_name, secure_upload), 
        bot.loop
    )

    return {"status": "success", "message": f"{len(files)} files queued for upload."}

@app.route('/download', methods=['POST'])
def download_route():
    server_id = request.form.get('server_id')
    filename = request.form.get('files')
    # ## We now get 'channels' from the select dropdown ##
    channel_name = request.form.get('channels') 
    logger.info(f"Download for '{filename}' from server '{server_id}' in channel '{channel_name}'")
    future = asyncio.run_coroutine_threadsafe(download_from_discord(server_id, channel_name, filename), bot.loop)
    file_path = future.result() 
    if file_path and os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
    else:
        return "File not found or failed to download.", 404

async def upload_folder_to_discord(files, server_id, channel_name, secure):
    guild = bot.get_guild(int(server_id))
    if not guild: return
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return

    # Determine the root folder name from the first file's path
    first_file_path = files[0].filename
    folder_name = first_file_path.split('/')[0] if '/' in first_file_path else 'upload'

    master_metadata = {
        "folder_name": folder_name,
        "encrypted": secure,
        "files": []
    }

    for file in files:
        original_filename = file.filename
        temp_path = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}")
        file.save(temp_path)

        try:
            if secure:
                with open(temp_path, 'rb') as f: data = f.read()
                encrypted_data = cipher.encrypt(data)
                with open(temp_path, 'wb') as f: f.write(encrypted_data)

            file_chunks = []
            file_size = os.path.getsize(temp_path)

            with open(temp_path, 'rb') as f:
                chunk_num = 0
                while True:
                    chunk_data = f.read(CHUNK_SIZE)
                    if not chunk_data: break
                    
                    chunk_id = f"{uuid.uuid4()}"
                    chunk_path = os.path.join(DATA_DIRECTORY, chunk_id)
                    with open(chunk_path, 'wb') as chunk_file:
                        chunk_file.write(chunk_data)
                    
                    # Upload each chunk as soon as it's created
                    await channel.send(file=discord.File(chunk_path, filename=chunk_id))
                    os.remove(chunk_path)
                    
                    file_chunks.append(chunk_id)
                    chunk_num += 1
            
            # Add this file's info to the master metadata
            master_metadata["files"].append({
                "path": original_filename,
                "size": file_size,
                "chunks": file_chunks
            })
            logger.info(f"Processed and uploaded chunks for '{original_filename}'")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # After processing all files, create and upload the master metadata
    metadata_filename = f"folder_{folder_name.replace(' ', '_')}_{uuid.uuid4()}_metadata.json"
    metadata_path = os.path.join(DATA_DIRECTORY, metadata_filename)
    metadata_content = json.dumps(master_metadata).encode()

    if secure:
        metadata_content = cipher.encrypt(metadata_content)

    with open(metadata_path, 'wb') as f:
        f.write(metadata_content)

    await channel.send(file=discord.File(metadata_path, filename=metadata_filename))
    os.remove(metadata_path)
    logger.info(f"✅ Successfully uploaded folder '{folder_name}' with {len(files)} files.")

## ## NEW DOWNLOAD FUNCTION FOR FOLDERS ## ##
async def download_folder_from_discord(server_id, channel_name, folder_name):
    guild = bot.get_guild(int(server_id))
    if not guild: return None
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return None

    # Find the correct metadata file for the folder
    metadata_message = None
    search_prefix = f"folder_{folder_name.replace(' ', '_')}_"
    async for message in channel.history(limit=1000):
        if message.attachments:
            if message.attachments[0].filename.startswith(search_prefix):
                metadata_message = message
                break
    
    if not metadata_message:
        logger.error(f"Metadata for folder '{folder_name}' not found.")
        return None

    # Download and parse metadata
    metadata_content = await metadata_message.attachments[0].read()
    try:
        if metadata_message.attachments[0].filename.startswith('enc_'):
             metadata_content = cipher.decrypt(metadata_content)
        metadata = json.loads(metadata_content.decode())
    except Exception as e:
        logger.error(f"Failed to parse metadata for folder '{folder_name}': {e}")
        return None

    is_encrypted = metadata.get("encrypted", False)
    zip_buffer = io.BytesIO()

    # Create a zip file in memory
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Download and reassemble each file from the metadata manifest
        for file_info in metadata["files"]:
            original_path = file_info["path"]
            logger.info(f"Downloading chunks for '{original_path}'...")
            
            file_data = bytearray()
            for chunk_id in file_info["chunks"]:
                chunk_message = None
                async for message in channel.history(limit=2000):
                    if message.attachments and message.attachments[0].filename == chunk_id:
                        chunk_message = message
                        break
                if chunk_message:
                    chunk_content = await chunk_message.attachments[0].read()
                    file_data.extend(chunk_content)
                else:
                    logger.error(f"Chunk '{chunk_id}' for file '{original_path}' not found!")
                    # Continue to try and assemble the rest of the zip
                    continue 

            if is_encrypted:
                file_data = cipher.decrypt(bytes(file_data))

            # Add the reassembled file to the zip archive
            zf.writestr(original_path, bytes(file_data))
            logger.info(f"Added '{original_path}' to zip archive.")

    zip_buffer.seek(0)
    return zip_buffer

# --- Main Execution ---
def run_flask():
    app.run(use_reloader=False, port=5000, host="0.0.0.0")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)