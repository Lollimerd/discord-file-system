from flask import Flask, request, render_template, send_file
import discord, os, threading, logging, json, colorlog
from discord.ext import commands
from dis_commands import *

# Initialize the Flask app
app = Flask(__name__)

# Discord bot setup
# bot = commands.Bot(command_prefix="!", intents=intents)
TOKEN = os.getenv('bot_token')

# Setup logging
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

kb = 1024
mb = kb * 1024
gb = mb * 1024

chunk_size = 10 * mb  # find max according to discord api docs

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file(): # handle input channel & filename
    # Save the file to the uploads directory
    file = request.files['file']
    file_path = os.path.join(DATA_DIRECTORY, file.filename)
    file.save(file_path)
    if 'file' not in request.files or 'channel' not in request.form:
        return {'error': 'File and channel name are required'}, 400
    if file.filename == '':
        return {'error': 'No selected file'}, 400
    logger.info(f"{file} has been saved to {file_path}")
    
    channel_name = request.form['channel']
    # Check if the channel exists
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name)
    if channel is None:
        return f'Channel "{channel_name}" not found.', 400
    logger.info(f"Channel {channel_name} found\n")

    # Run the Discord bot task to upload the file
    bot.loop.create_task(upload_to_discord(file_path, file.filename, channel_name))
    return render_template('uploaded.html')

# configuring splitting of chunks and file formatting for chunks & metadata
async def upload_to_discord(file_path, filename, channel_name):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if channel:
        print(f"Uploading file: {file_path}")
        # get file size from upload
        file_size_bytes = os.path.getsize(file_path)
        file_size_kb = file_size_bytes / 1024   # 1024 bytes = 1 kilo byte
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

        # determine if need chunk
        if file_size_bytes < chunk_size: # single file, no need chunking
            logger.info(f"file does not need chunking, preparing uploading...")
            # Create metadata for the single chunk
            metadata = {
                "original_filename": filename,
                "chunks": [filename.replace(" ", "_")]
            }
            metadata_filename = os.path.join(DATA_DIRECTORY, f"{filename.replace(' ', '_')}_metadata.json")
            with open(metadata_filename, 'w') as metadata_file:
                json.dump(metadata, metadata_file)
                
            # Upload metadata
            await channel.send(file=discord.File(metadata_filename))           
            os.remove(metadata_filename)  # Remove the metadata file after uploading
            logger.info(f"sent metadata {metadata_filename} and deleted in {file_path}")
            
            # Upload file
            with open(file_path, 'rb') as file:
                await channel.send(file=discord.File(file, filename=filename.replace(" ", "_")))
            os.remove(file_path)  # Remove the original file after uploading
            logger.info(f"file has been sent and deleted from {file_path}")
            return            
        else: # requires chunking
            # Split the file into 25 MB chunks and get the metadata filename
            chunks, metadata_filename = split_file(file_path, chunk_size, filename)
            logger.info("file has been split into chunks & obtain metadata filename")
            
            # Send the metadata file
            await channel.send(file=discord.File(metadata_filename))
            os.remove(metadata_filename)  # Remove the metadata file after uploading
            logger.info(f"sent {metadata_filename} and removed from {file_path}")
            
            # Send each chunk file
            for chunk in chunks:
                # Replace spaces with underscores in the chunk filename
                chunk_filename = os.path.basename(chunk).replace(" ", "_")
                await channel.send(file=discord.File(chunk, filename=chunk_filename))
                os.remove(chunk)  # Remove the chunk after uploading
                
            # Remove the original file after splitting and uploading
            os.remove(file_path)
            logger.info(f"sent {chunk_filename} and removed from {file_path}")
    else:
        logging.error(f'Channel named "{channel}" not found.')

def split_file(file_path, chunk_size, filename):
    """Splits a file into chunks of specified size and saves metadata."""
    chunks = [] # lists of chunk filenames
    filesize = os.path.getsize(file_path)
    file_base, file_ext = os.path.splitext(filename) # ext means file extension
    logger.info(f"\ncombining {file_base} \nwith extension {file_ext}")
    with open(file_path, 'rb') as f:
        chunk_num = 0       
        while True:
            chunk = f.read(chunk_size) # read file in chunk size
            if not chunk: # function only for files larger than 25MB
                break
            base_name = file_base.replace(" ", "_") # replace space with underscore
            chunk_filename = f"{base_name}_part_{len(chunks)}{file_ext}"  # chunk labelling
            with open(chunk_filename, 'wb') as chunk_file:
                chunk_file.write(chunk)  # writes chunk
                logger.info("writing chunk")
            chunks.append(chunk_filename)
            chunk_num += 1
            logger.info(f"{chunk_num} chunks written")
        logger.info(f"total number of chunks: {chunk_num}")
    # creating of metadata
    metadata = {
        "original_filename": filename,
        "file_size": filesize,
        "no of chunks": chunk_num,
        "chunks": chunks
    }
    metadata_filename = os.path.join(DATA_DIRECTORY, f"{file_base}_metadata.json")
    with open(metadata_filename, 'w') as metadata_file:
        json.dump(metadata, metadata_file)
    logger.info(f"\nmetadata {metadata_filename} created")
    return chunks, metadata_filename


@app.route('/download', methods=['POST'])
def download_file():
    channel_name = request.form['channels']
    filename = request.form['files']
    logger.info(f"obtaining {channel_name} & {filename}...")
    bot.loop.create_task(download_files(channel_name, filename))
    return "downloading...", 200

async def download_files(channel_name, filename):
    # retrieving channel from server
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name, type=discord.ChannelType.text)
    if not channel:
        return f"Channel {channel} not found.", 404
    logger.info(f"Channel {channel} found \n")
    
    # retrieve message containing metadata file
    download_filename = filename.replace(" ", "_")
    metadata_filename = f"{download_filename}_metadata.json"
    metadata_message = None
    logger.info(f"retrieving contents from {metadata_filename}")
    async for message in channel.history(limit=500):  # Adjust the limit as needed
        for attachment in message.attachments:           
            if attachment.filename == metadata_filename:
                print(f"Checking attachment: {attachment.filename}")
                metadata_message = message
                break
        if metadata_message:
            break
    if metadata_message is None:
        logging.error(f'Metadata file {metadata_filename} not found in channel {channel_name}.')
        return "Metadata not found.", 404
    
    # download metadata
    metadata_attachment = metadata_message.attachments[0]
    metadata_content = await metadata_attachment.read()
    metadata = json.loads(metadata_content.decode())
    original_filename = metadata["original_filename"]
    logger.info(f"creating supporting documents: \n\n{metadata} \n{original_filename}")
    
    # Reassemble the file
    reassembled_file_path = os.path.join(DATA_DIRECTORY, original_filename)
    try:
        with open(reassembled_file_path, 'wb') as reassembled_file:
            chunk_num = 0
            for chunk_filename in metadata["chunks"]:                               
                chunk_message = None
                logger.info("checking attachments...")
                async for message in channel.history(limit=500):  # Adjust the limit as needed
                    for attachment in message.attachments:
                        if attachment.filename == chunk_filename:
                            chunk_message = message
                            logger.info(f"chunk valid")
                            chunk_num += 1
                            break
                    if chunk_message:
                        logger.info(f"writing chunk {chunk_num}")
                        break
                if chunk_message is None:
                    logger.error(f'Chunk file {chunk_filename} not found in channel {channel_name}.')
                    return f"Chunk {chunk_filename} not found.", 404
                
                chunk_attachment = chunk_message.attachments[0]
                chunk_content = await chunk_attachment.read() # read attachments
                reassembled_file.write(chunk_content)
                logger.info(f"\nassembling chunks...")
               
            print(f"written {chunk_num} chunks")
    except Exception as e:
        logger.error(f"Failed to reassemble file: {e}")
        return f"Failed to reassemble file: {e}", 500
    
    logger.info("File has been reassembled and saved to uploads directory")
    return send_file(reassembled_file_path, as_attachment=True, download_name=original_filename), render_template('index.html')
         
def just_in_case(metadata, metadata_filename):
    # Clean up chunk files after reassembly
    for chunk in metadata["chunks"]:
        try:
            os.remove(chunk.replace(" ", "_"))
        except Exception as e:
            logging.warning(f"Directory does not contain chunk file {chunk}: {e}")
    try:
        os.remove(metadata_filename)  # Remove metadata file after reassembly
    except Exception as e:
        logging.warning(f"Directory does not contain metadata file {metadata_filename}: {e}")

# Run the Flask app in a separate thread
def run_flask():
    app.run(use_reloader=False, port=5000, host="0.0.0.0")

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    bot.run(TOKEN)
