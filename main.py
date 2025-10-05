from flask import Flask, request, render_template, send_file, redirect, url_for, flash
import discord, os, threading, json, asyncio, uuid, shutil
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from utils.util import (
    find_guild_by_name, 
    fetch_channels_from_guild, 
    logger,
    upload_single_file,
    upload_folder,
    download_from_discord,
    _process_and_chunk_file,
    DATA_DIRECTORY,
    )
from dis_commands import *

load_dotenv()

app = Flask(__name__)
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
            processed_chunks, processed_basenames = _process_and_chunk_file(temp_file_path, secure_upload)
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