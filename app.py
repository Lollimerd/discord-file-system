# app.py

from flask import Flask, request, render_template, send_file, redirect, url_for
import discord, os, threading, logging, json, asyncio, colorlog
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from dis_commands import *

load_dotenv()

# Initialize the Flask app
app = Flask(__name__)

# Bot token and encryption key from .env file
TOKEN = os.getenv("bot_token")
ENCRYPTION_KEY = os.getenv("enc_key").encode()
cipher = Fernet(ENCRYPTION_KEY)

# Configure colorlog for colored output
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)s: %(message)s',
    log_colors={
        'DEBUG': 'bold_cyan', 'INFO': 'bold_green', 'WARNING': 'bold_yellow',
        'ERROR': 'red', 'CRITICAL': 'bold_red',
    }
))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Directory for temporary file storage
DATA_DIRECTORY = 'transfer'
if not os.path.exists(DATA_DIRECTORY):
    os.makedirs(DATA_DIRECTORY)

# File size constants
CHUNK_SIZE = 20 * 1024 * 1024  # Discord's file size limit is now 25MB, 20MB is a safe chunk size

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files or 'channel' not in request.form:
        return 'File and channel name are required', 400
    
    file = request.files['file']
    if file.filename == '':
        return 'No selected file', 400

    channel_name = request.form['channel']
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if channel is None:
        return f'Channel "{channel_name}" not found.', 400

    ## Check if the encryption checkbox was ticked
    secure_upload = request.form.get('encrypt') == 'true'

    file_path = os.path.join(DATA_DIRECTORY, file.filename)
    file.save(file_path)
    logger.info(f"File saved to {file_path}")

    # Run the Discord bot task to upload the file
    bot.loop.create_task(upload_to_discord(file_path, file.filename, channel_name, secure_upload))
    return render_template('uploaded.html')

@app.route('/download', methods=['POST'])
def download_route():
    channel_name = request.form['channels']
    filename = request.form['files']
    logger.info(f"Initiating download for '{filename}' from channel '{channel_name}'")
    
    # Run the download task and wait for it to complete to get the file path
    future = asyncio.run_coroutine_threadsafe(download_from_discord(channel_name, filename), bot.loop)
    file_path = future.result() # This will block until the download is done

    if file_path and os.path.exists(file_path):
        logger.info(f"Sending file: {file_path}")
        return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
    else:
        logger.error(f"File could not be downloaded or found.")
        return "File not found or failed to download.", 404


# --- Discord Logic ---

async def upload_to_discord(file_path, filename, channel_name, secure):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if not channel:
        logger.error(f'Channel "{channel_name}" not found.')
        return

    ## Conditionally encrypt the file
    if secure:
        logger.info("Encryption enabled. Encrypting file...")
        with open(file_path, 'rb') as f:
            data = f.read()
        encrypted_data = cipher.encrypt(data)
        with open(file_path, 'wb') as f:
            f.write(encrypted_data)
        logger.info("File encrypted successfully.")

    # Chunking logic (handles both large and small files)
    chunks = []
    file_size = os.path.getsize(file_path)

    if file_size > CHUNK_SIZE:
        logger.info("File is large, splitting into chunks...")
        with open(file_path, 'rb') as f:
            chunk_num = 0
            while True:
                chunk_data = f.read(CHUNK_SIZE)
                if not chunk_data:
                    break
                base_name, ext = os.path.splitext(filename)
                chunk_filename = os.path.join(DATA_DIRECTORY, f"{base_name.replace(' ', '_')}_part_{chunk_num}{ext}")
                with open(chunk_filename, 'wb') as chunk_file:
                    chunk_file.write(chunk_data)
                chunks.append(chunk_filename)
                chunk_num += 1
    else:
        logger.info("File is small, no chunking needed.")
        chunks.append(file_path)

    # Prepare and send metadata
    metadata = {
        "original_filename": filename,
        "chunks": [os.path.basename(c).replace(' ', '_') for c in chunks],
        "encrypted": secure  ## Add the encryption flag to metadata
    }
    metadata_filename = os.path.join(DATA_DIRECTORY, f"{filename.replace(' ', '_')}_metadata.json")
    
    metadata_content = json.dumps(metadata).encode()
    ## Conditionally encrypt metadata
    if secure:
        metadata_content = cipher.encrypt(metadata_content)
        
    with open(metadata_filename, 'wb') as f:
        f.write(metadata_content)

    await channel.send(file=discord.File(metadata_filename))
    logger.info("Metadata sent.")
    os.remove(metadata_filename)

    # Send each chunk
    for chunk_path in chunks:
        await channel.send(file=discord.File(chunk_path, filename=os.path.basename(chunk_path).replace(' ', '_')))
        logger.info(f"Sent chunk: {os.path.basename(chunk_path)}")
        if chunk_path != file_path: # Don't remove the original if it wasn't chunked
             os.remove(chunk_path)
    
    os.remove(file_path) # Clean up the original (or encrypted) file
    logger.info("Upload complete and local files cleaned up.")


async def download_from_discord(channel_name, filename):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if not channel:
        logger.error(f"Channel '{channel_name}' not found.")
        return None

    # Find and download metadata
    metadata_filename = f"{filename.replace(' ', '_')}_metadata.json"
    metadata_message = None
    async for message in channel.history(limit=500):
        if message.attachments and message.attachments[0].filename == metadata_filename:
            metadata_message = message
            break
    
    if not metadata_message:
        logger.error(f"Metadata '{metadata_filename}' not found.")
        return None

    logger.info("Metadata found. Downloading and parsing...")
    metadata_attachment = metadata_message.attachments[0]
    encrypted_metadata_content = await metadata_attachment.read()

    try:
        # First, try to decrypt. If it fails, assume it's plaintext.
        decrypted_metadata_content = cipher.decrypt(encrypted_metadata_content)
        metadata = json.loads(decrypted_metadata_content.decode())
        logger.info("Metadata was encrypted and has been decrypted.")
    except Exception:
        metadata = json.loads(encrypted_metadata_content.decode())
        logger.info("Metadata was not encrypted.")

    original_filename = metadata["original_filename"]
    is_encrypted = metadata.get("encrypted", False) ## Check the encrypted flag

    # Reassemble the file from chunks
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
                return None

            chunk_content = await chunk_message.attachments[0].read()
            reassembled_file.write(chunk_content)
            logger.info(f"Downloaded and assembled chunk: {chunk_filename}")

    ## Conditionally decrypt the reassembled file
    if is_encrypted:
        logger.info("File is encrypted. Decrypting now...")
        with open(reassembled_file_path, 'rb') as f:
            encrypted_data = f.read()
        decrypted_data = cipher.decrypt(encrypted_data)
        with open(reassembled_file_path, 'wb') as f:
            f.write(decrypted_data)
        logger.info("File decrypted successfully.")
    
    logger.info(f"File reassembly complete. Path: {reassembled_file_path}")
    return reassembled_file_path

# --- Main Execution ---

def run_flask():
    # Use '0.0.0.0' to make it accessible on your network
    app.run(use_reloader=False, port=5000, host="0.0.0.0")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)