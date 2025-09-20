from flask import Flask, request, render_template, send_file, redirect, url_for, flash
import discord, os, threading, json, asyncio, uuid
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from utils.util import find_guild_by_name, fetch_channels_from_guild, logger
from dis_commands import *

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24) 

TOKEN = os.getenv("bot_token")
ENCRYPTION_KEY = os.getenv("enc_key").encode()
cipher = Fernet(ENCRYPTION_KEY)

DATA_DIRECTORY = 'Data'
if not os.path.exists(DATA_DIRECTORY): os.makedirs(DATA_DIRECTORY)
CHUNK_SIZE = 10 * 1024 * 1024

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/select_server', methods=['POST'])
def select_server():
    server_name = request.form.get('server_name')
    if not server_name:
        flash("Server name cannot be empty.")
        return redirect(url_for('index'))

    # Find the guild by name to get its ID
    future = asyncio.run_coroutine_threadsafe(find_guild_by_name(server_name), bot.loop)
    server_id = future.result()

    if server_id:
        # Redirect to the main page using the found server ID
        return redirect(url_for('server_page', server_id=server_id))
    else:
        flash(f"Could not find server '{server_name}'. Please check the name and ensure the bot is a member of that server.")
        return redirect(url_for('index'))

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

async def upload_to_discord(file_path, original_filename, server_id, channel_name, secure):
    guild = bot.get_guild(int(server_id))
    if not guild:
        logger.error(f"Upload failed: Guild {server_id} not found.")
        return
    
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        logger.error(f'Upload failed: Channel "{channel_name}" not found in server {guild.name}.')
        return

    try:
        if secure:
            logger.info(f"Encrypting '{original_filename}'...")
            with open(file_path, 'rb') as f: data = f.read()
            encrypted_data = cipher.encrypt(data)
            with open(file_path, 'wb') as f: f.write(encrypted_data)

        chunks = []
        file_size = os.path.getsize(file_path)

        if file_size > CHUNK_SIZE:
            logger.info(f"Chunking '{original_filename}'...")
            
            # ## Use the temporary file's name for chunking to avoid path errors ##
            temp_basename = os.path.basename(file_path)
            base_name, ext = os.path.splitext(temp_basename)

            with open(file_path, 'rb') as f:
                chunk_num = 0
                while True:
                    chunk_data = f.read(CHUNK_SIZE)
                    if not chunk_data: break
                    
                    chunk_filename = os.path.join(DATA_DIRECTORY, f"{base_name}_part_{chunk_num}{ext}")
                    with open(chunk_filename, 'wb') as chunk_file:
                        chunk_file.write(chunk_data)
                    chunks.append(chunk_filename)
                    chunk_num += 1
        else:
            chunks.append(file_path)

        # ## Note: 'original_filename' is passed to metadata, preserving the path ##
        metadata = {
            "original_filename": original_filename,
            "chunks": [os.path.basename(c).replace(' ', '_') for c in chunks],
            "encrypted": secure
        }
        metadata_filename = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}_metadata.json")
        
        metadata_content = json.dumps(metadata).encode()
        if secure: metadata_content = cipher.encrypt(metadata_content)
            
        with open(metadata_filename, 'wb') as f: f.write(metadata_content)

        await channel.send(file=discord.File(metadata_filename))
        os.remove(metadata_filename)

        for chunk_path in chunks:
            await channel.send(file=discord.File(chunk_path, filename=os.path.basename(chunk_path).replace(' ', '_')))
            if chunk_path != file_path:
                os.remove(chunk_path)
            logger.info("Waiting 0.5s to avoid rate limits...")
            await asyncio.sleep(0.5) # 🐢 Proactive delay

        logger.info(f"Successfully uploaded '{original_filename}'.")
    except Exception as e:
        logger.error(f"An error occurred during upload for '{original_filename}': {e}")
    finally:
        # ## Clean up the main temporary file ##
        if os.path.exists(file_path):
            os.remove(file_path)

@app.route('/upload', methods=['POST'])
def upload_file():
    server_id = request.form.get('server_id')
    channel_name = request.form.get('channel')
    secure_upload = request.form.get('encrypt') == 'true'
    files = request.files.getlist('files[]')

    if not all([server_id, channel_name, files]):
        return 'Missing form data', 400

    total_files = len(files)
    for file in files:
        if file.filename == '':
            total_files -= 1
            continue
        original_filename = file.filename

        # Create a unique filename to prevent overwrites
        _, ext = os.path.splitext(original_filename)
        unique_filename = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(DATA_DIRECTORY, unique_filename)
        file.save(file_path)
        logger.info(f"File '{original_filename}' saved temporarily as '{unique_filename}'")

        # Schedule the coroutine to run on the bot's event loop
        future = asyncio.run_coroutine_threadsafe(
            upload_to_discord(file_path, original_filename, server_id, channel_name, secure_upload), 
            bot.loop
        )

        # ✅ **KEY CHANGE HERE** ✅
        # Wait for the future to complete. This blocks the loop
        # until the current file (metadata + all chunks) is fully uploaded.
        future.result()

    # The message now accurately reflects that the uploads are complete, not just queued.
    return {"status": "success", "message": f"{total_files} files uploaded successfully."}

async def download_from_discord(server_id, channel_name, filename):
    """ Downloads and reassembles a file from Discord messages. """
    # We now get 'channel_name' from the select dropdown ##
    guild = bot.get_guild(int(server_id))
    if not guild:
        logger.error(f"Download failed: Guild {server_id} not found.")
        return None

    # Get the channel object from the guild
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        logger.error(f"Download failed: Channel '{channel_name}' not found in server {guild.name}.")
        return None
    
    # ## Look for the metadata message first ##
    metadata_filename = f"{filename.replace(' ', '_')}_metadata.json"
    metadata_message = None

    # Look for the metadata message in the channel history
    async for message in channel.history(limit=500):
        if message.attachments and message.attachments[0].filename == metadata_filename:
            metadata_message = message
            break
    
    # ## If metadata not found, abort ##
    if not metadata_message:
        logger.error(f"Metadata '{metadata_filename}' not found.")
        return None
     
    logger.info("Metadata found. Downloading and parsing...")
    metadata_attachment = metadata_message.attachments[0]
    encrypted_metadata_content = await metadata_attachment.read()

    # Try to decrypt metadata; if fails, assume it's not encrypted
    try:
        decrypted_metadata_content = cipher.decrypt(encrypted_metadata_content)
        metadata = json.loads(decrypted_metadata_content.decode())
        logger.info("Metadata was encrypted and has been decrypted.")
    except Exception:
        metadata = json.loads(encrypted_metadata_content.decode())
        logger.info("Metadata was not encrypted.")

    original_filename = metadata["original_filename"]
    is_encrypted = metadata.get("encrypted", False)
    reassembled_file_path = os.path.join(DATA_DIRECTORY, original_filename)

    with open(reassembled_file_path, 'wb') as reassembled_file:
        for chunk_filename in metadata["chunks"]:
            chunk_message = None
            async for message in channel.history(limit=1000):
                if message.attachments and message.attachments[0].filename == chunk_filename:
                    chunk_message = message
                    break
            if not chunk_message:
                logger.error(f"Chunk '{chunk_filename}' not found!")
                os.remove(reassembled_file_path)
                return None
            chunk_content = await chunk_message.attachments[0].read()
            reassembled_file.write(chunk_content)
            logger.info(f"Downloaded and assembled chunk: {chunk_filename}")

    if is_encrypted:
        logger.info("File is encrypted. Decrypting now...")
        with open(reassembled_file_path, 'rb') as f: encrypted_data = f.read()
        decrypted_data = cipher.decrypt(encrypted_data)
        with open(reassembled_file_path, 'wb') as f:
            f.write(decrypted_data)
        logger.info("File decrypted successfully.")
    logger.info(f"File reassembly complete. Path: {reassembled_file_path}")
    return reassembled_file_path

@app.route('/download', methods=['POST'])
def download_route():
    server_id = request.form.get('server_id')
    filename = request.form.get('files')

    # We now get 'channels' from the select dropdown 
    channel_name = request.form.get('channels') 
    logger.info(f"Download for '{filename}' from server '{server_id}' in channel '{channel_name}'")
    future = asyncio.run_coroutine_threadsafe(download_from_discord(server_id, channel_name, filename), bot.loop)
    file_path = future.result() 

    if file_path and os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
    else:
        return "File not found or failed to download.", 404

# --- Main Execution ---
def run_flask():
    app.run(use_reloader=False, port=5000, host="0.0.0.0")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)