from flask import Flask, request, render_template, send_file
import discord, os, threading, logging, json, asyncio, colorlog
from discord.ext import commands
from cryptography.fernet import Fernet
from dis_commands import *
# Initialize the Flask app
app = Flask(__name__)

# bot token
TOKEN = os.getenv('bot_token')

# Configure colorlog for colored output
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)s: %(message)s',
    log_colors={
        'DEBUG': 'bold_cyan',
        'INFO': 'bold_green',
        'WARNING': 'bold_yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
))

logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# Replace with the directory where you want to store uploaded files
DATA_DIRECTORY = 'Data'

# if no such directory, create one
if not os.path.exists(DATA_DIRECTORY):
    os.makedirs(DATA_DIRECTORY)

# creation of metadata directory
metadata_directory = 'metadata'

chunk_size = 10 * 1024 * 1024  # find max according to discord api docs

kb = 1024
mb = kb * 1024
gb = mb * 1024

# Encrypt the file
# encryption_key = Fernet.generate_key()
encryption_key = os.getenv("enc_key").encode()
cipher = Fernet(encryption_key)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

# flask
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files or 'channel' not in request.form:
        return {'error': 'File and channel name are required'}, 400
    file = request.files['file']
    file_path = os.path.join(DATA_DIRECTORY, file.filename)
    if file.filename == '':
        return {'error': 'No selected file'}, 400
    file.save(file_path)
    logging.info(f"{file} has been saved to {file_path}")

    channel_name = request.form['channel']
    # Check if the channel exists
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if channel is None:
        return f'Channel "{channel_name}" not found.', 400
    logging.info(f"Channel {channel_name} found\nencrypting...")

    # encryption process
    with open(file_path, 'rb') as f:
        data = f.read()
        logging.info(f"reading file")
    encrypted_data = cipher.encrypt(data)
    logging.info(f"encrypting data")
    encrypted_file_path = file_path
    with open(encrypted_file_path, 'wb') as f:
        f.write(encrypted_data)
        logging.info(f"written back {f}")

    logging.info(f"initiating send sequence")
    # Run the Discord bot task to upload the file
    bot.loop.create_task(upload_to_discord(encrypted_file_path, file.filename, channel_name, encryption_key))
    return render_template('uploaded.html')

async def upload_to_discord(file_path, filename, channel_name, encryption_key):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if channel:
        logging.info(f"Uploading file: {file_path}")
        
        file_size_bytes = os.path.getsize(file_path)
        file_size_kb = file_size_bytes / 1024  # 1024 bytes = 1 kilo byte
        file_size_mb = file_size_kb / 1024
        file_size_gb = file_size_mb / 1024

        if file_size_bytes < kb:
            logger.info(f"File size: {file_size_bytes:.3f} Bytes")
        if kb < file_size_bytes < mb:
            logger.info(f"File size: {file_size_kb:.2f} KB")
        if mb < file_size_bytes < gb:
            logger.info(f"File size: {file_size_mb:.2f} MB")
        if file_size_bytes > gb:
            logger.info(f"File size: {file_size_gb:.2f} GB")

        # no chunking
        if file_size_bytes < chunk_size:
            logger.info(f"file does not need chunking, preparing uploading...")
            # Create metadata for the single chunk
            metadata = {
                "original_filename": filename,
                "chunks": [filename.replace(" ", "_")],
                "encryption_key": encryption_key.decode()
            }
            metadata_filename = os.path.join(DATA_DIRECTORY, f"{filename.replace(' ', '_')}_metadata.json")
            # Encrypt and save metadata            
            encrypted_metadata = cipher.encrypt(json.dumps(metadata).encode())
            with open(metadata_filename, 'wb') as metadata_file:
                metadata_file.write(encrypted_metadata)
                
            # Upload metadata
            await channel.send(file=discord.File(metadata_filename))
            os.remove(metadata_filename)  # Remove the metadata file after uploading
            logging.info(f"sent metadata {metadata_filename} and deleted in {file_path}")

            # Upload the single chunk (entire file)
            with open(file_path, 'rb') as file:
                await channel.send(file=discord.File(file, filename=filename.replace(" ", "_")))
            os.remove(file_path)  # Remove the encrypted file after uploading
            logging.info(f"file has been sent and deleted from {file_path}")
            return logging.info("done")

        # split sequence
        if file_size_bytes > chunk_size:
            logging.info("initiating split sequence")
            # Split the file into chunks and get the metadata filename
            chunks, metadata_filename = split_file(file_path, chunk_size, filename, encryption_key)
            logging.info("file has been split into chunks & obtain metadata filename")

            # Send the metadata file
            await channel.send(file=discord.File(metadata_filename))
            os.remove(metadata_filename)  # Remove the metadata file after uploading
            logging.info(f"sent {metadata_filename} and removed from {file_path}")

            # Send each chunk file
            for chunk in chunks:
                chunk_filename = os.path.basename(chunk).replace(" ", "_")
                await channel.send(file=discord.File(chunk, filename=chunk_filename))
                os.remove(chunk)  # Remove the chunk after uploading
                logging.info(f"sent {chunk_filename} and removed from {file_path}")
            os.remove(file_path)  # Remove the encrypted file after splitting and uploading
            logger.info(f"Process done")
        else:
            pass
    else:
        logging.error(f'Channel named "{channel_name}" not found.')
        return {"error": "channel name not found"}

def split_file(file_path, chunk_size, filename, encryption_key):
    chunks = []
    file_base, file_ext = os.path.splitext(filename)
    logger.info(f"\nsplitting {file_base} \nwith extension {file_ext}")

    with open(file_path, 'rb') as f:
        chunk_num = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            base_name = file_base.replace(" ", "_")
            chunk_filename = os.path.join(DATA_DIRECTORY, f"{base_name}_part_{chunk_num}{file_ext}")
            with open(chunk_filename, 'wb') as chunk_file:
                chunk_file.write(chunk)
            chunks.append(chunk_filename)
            chunk_num += 1
        logging.info(f"total number of chunks: {chunk_num}")
    metadata = {
        "original_filename": filename,
        "chunks": [os.path.basename(chunk) for chunk in chunks],
        "encryption key": encryption_key.decode()
    }
    metadata_filename = os.path.join(DATA_DIRECTORY, f"{file_base}_metadata.json")
    encrypted_metadata = cipher.encrypt(json.dumps(metadata).encode())
    with open(metadata_filename, 'wb') as metadata_file:
        metadata_file.write(encrypted_metadata)

    logging.info(f"metadata for chunks {metadata_filename} created")
    return chunks, metadata_filename


@app.route('/download', methods=['POST'])
def download_file():
    channel_name = request.form['channels']
    filename = request.form['files']
    print(f"obtaining channel {channel_name} & filename {filename}...")
    asyncio.run_coroutine_threadsafe(download(channel_name, filename), bot.loop)
    return "downloading...", 200

async def download(channel_name, filename):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if not channel:
        return "Channel not found.", 404
    logging.info(f"found channel: {channel}")
    
    download_filename = filename.replace(" ", "_")
    metadata_filename = f"{download_filename}_metadata.json"
    metadata_message = None
    logging.info(f"retrieving contents from {metadata_filename}")
    async for message in channel.history(limit=100):  # Adjust the limit as needed
        for attachment in message.attachments:
            if attachment.filename == metadata_filename:
                logging.info(f"Check for metadata: {attachment.filename}")
                metadata_message = message
                break
        if metadata_message:
            break
           
    if metadata_message is None:
        logging.error(f'Metadata file {metadata_filename} not found in channel {channel_name}.')
        return "Metadata not found.", 404
    logging.info(f"metadata {metadata_filename} found")

    # download metadata
    metadata_attachment = metadata_message.attachments[0]
    encrypted_metadata_content = await metadata_attachment.read()
    logging.info(f"reading encrypted metadata...")
    try:  # decrypt metadata
        decrypted_metadata_content = cipher.decrypt(encrypted_metadata_content)
        metadata = json.loads(decrypted_metadata_content.decode())
        logging.info(f"metadata {metadata} loaded")
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode metadata: {e}")
        print(f"Failed to decode metadata: {e}", 400)

    original_filename = metadata["original_filename"]
    print(f"creating supporting documents: \n\n{metadata} {original_filename} \n{cipher}")

    # reassemble file
    reassembled_file_path = os.path.join(DATA_DIRECTORY, original_filename)
    try:
        with open(reassembled_file_path, 'wb') as reassembled_file:
            chunk_num = 0
            for chunk_filename in metadata["chunks"]:
                chunk_filename = chunk_filename.replace(" ", "_")
                chunk_message = None
                async for message in channel.history(limit=1000):  # Adjust the limit as needed
                    for attachment in message.attachments:
                        if attachment.filename == chunk_filename:
                            print(f"checking attachments: {attachment.filename}")
                            chunk_message = message
                            chunk_num += 1
                            print(f"{chunk_num} chunk valid")
                            break
                    if chunk_message:
                        print("chunk valid")
                        break
                if chunk_message is None:
                    logging.error(f'Chunk file {chunk_filename} not found in channel {channel_name}.')
                    return f"Chunk {chunk_filename} not found.", 404

                # writing chunks process
                chunk_attachment = chunk_message.attachments[0]
                chunk_content = await chunk_attachment.read()
                reassembled_file.write(chunk_content)

        # Decrypt the reassembled file
        with open(reassembled_file_path, 'rb') as encrypted_file:
            encrypted_data = encrypted_file.read()
        decrypted_data = cipher.decrypt(encrypted_data)
        with open(reassembled_file_path, 'wb') as decrypted_file:
            decrypted_file.write(decrypted_data)

    except Exception as e:
        logging.error(f"Failed to reassemble file: {e}")
        return f"Failed to reassemble file: {e}", 500

    send_file(reassembled_file_path, as_attachment=True, download_name=original_filename)
    print("File has been reassembled and saved to uploads directory")
    return render_template('uploaded.html')


# Run the Flask app in a separate thread
def run_flask():
    app.run(use_reloader=False, port=5000, host="0.0.0.0")

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    bot.run(TOKEN)
