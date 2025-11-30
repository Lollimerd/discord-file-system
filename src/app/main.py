from flask import Flask, request, render_template, send_file, redirect, url_for, flash
import discord, threading, json, asyncio, uuid, shutil, os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from ..dis_commands import bot
from ..utils.util import (
    logger,
    cipher,
    DATA_DIRECTORY,
    find_guild_by_name,
    fetch_channels_from_guild,
    process_and_chunk_file,
)

load_dotenv()

# Calculate the path to the 'template' folder in the project root
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = os.urandom(24) 

TOKEN = os.getenv("bot_token")

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


# --- Upload Logic ---
async def upload_single_file(file_path, original_filename, server_id, channel_name, secure):
    """Handles the upload process for a single file using the unified chunker."""
    guild = bot.get_guild(int(server_id))
    if not guild: return logger.error(f"Upload failed: Guild {server_id} not found.")
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return logger.error(f'Upload failed: Channel "{channel_name}" not found.')

    try:
        # Use the unified helper for all processing and naming
        chunk_paths, chunk_basenames = process_and_chunk_file(file_path, secure)

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

@app.route('/upload', methods=['POST'])
def upload_handler():
    server_id = request.form.get('server_id')
    channel_name = request.form.get('channel')
    secure_upload = request.form.get('encrypt') == 'true'
    files = request.files.getlist('files[]')

    if not all([server_id, channel_name, files]):
        return 'Missing form data', 400

    is_folder_upload = any('/' in f.filename for f in files if f.filename)

    if is_folder_upload:
        logger.info("Folder upload detected.")
        folder_tree = {}
        all_chunk_paths = []
        folder_name = os.path.dirname(files[0].filename) or "upload"

        for file in files:
            if not file.filename: continue
            
            temp_file_path = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}")
            file.save(temp_file_path)

            # Use the unified helper for processing
            processed_chunks, processed_basenames = process_and_chunk_file(temp_file_path, secure_upload)
            all_chunk_paths.extend(processed_chunks)

            # Build the folder tree structure
            path_parts = file.filename.split('/')
            current_level = folder_tree
            for part in path_parts[:-1]:
                current_level = current_level.setdefault(part, {"type": "directory", "children": {}})["children"]
            current_level[path_parts[-1]] = {"type": "file", "chunks": processed_basenames}

        final_metadata = {
            "upload_type": "folder", "folder_name": folder_name, "encrypted": secure_upload,
            "tree": folder_tree.get(folder_name, {}).get("children", folder_tree)
        }
        
        future = asyncio.run_coroutine_threadsafe(upload_folder(final_metadata, all_chunk_paths, server_id, channel_name), bot.loop)
        future.result()
        return {"status": "success", "message": f"Folder '{folder_name}' uploaded."}

    else:
        logger.info("Individual file upload detected.")
        for file in files:
            if not file.filename: continue
            
            temp_file_path = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}")
            file.save(temp_file_path)

            future = asyncio.run_coroutine_threadsafe(
                upload_single_file(temp_file_path, file.filename, server_id, channel_name, secure_upload),
                bot.loop
            )
            future.result()
        return {"status": "success", "message": f"{len(files)} files uploaded."}


# --- Download Logic ---
async def download_from_discord(server_id, channel_name, requested_path):
    """Downloads a file or folder, with synchronized and robust error handling."""
    # Get guild and channel
    guild = bot.get_guild(int(server_id))
    if not guild: return logger.error(f"Download failed: Guild {server_id} not found.")
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return logger.error(f"Download failed: Channel '{channel_name}' not found.")

    # Get metadata
    root_object_name = requested_path.split('/')[0]
    metadata_filename_to_find = f"{root_object_name}_metadata.json"
    
    # Build file cache
    logger.info("Building file cache from channel history...")
    file_cache = {
        attachment.filename: message
        async for message in channel.history(limit=2000)
        for attachment in message.attachments
    }
    logger.info(f"Cache built with {len(file_cache)} files.")

    # Get metadata
    metadata_message = file_cache.get(metadata_filename_to_find)
    if not metadata_message: return logger.error(f"Metadata for '{root_object_name}' not found.")

    encrypted_metadata_content = await metadata_message.attachments[0].read()
    try:
        metadata = json.loads(cipher.decrypt(encrypted_metadata_content))
    except Exception:
        metadata = json.loads(encrypted_metadata_content)
    
    is_encrypted = metadata.get("encrypted", False)

    # Get folder
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

@app.route('/download', methods=['POST'])
def download_route():
    server_id = request.form.get('server_id')
    filename = request.form.get('files')
    channel_name = request.form.get('channels') 
    logger.info(f"Download for '{filename}' from server '{server_id}' in channel '{channel_name}'")
    future = asyncio.run_coroutine_threadsafe(download_from_discord(server_id, channel_name, filename), bot.loop)
    file_path = future.result() 

    if file_path and os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
    else:
        flash(f"File '{filename}' not found or failed to download.")
        return redirect(url_for('server_page', server_id=server_id))
    
# --- Main Execution ---
def run_flask():
    app.run(use_reloader=False, port=5000, host="0.0.0.0")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)