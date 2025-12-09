import sys, os

# Add project root to sys.path to allow running this file directly
# Project root is 2 directories up from this file (src/app/main.py -> src/app -> src -> root)
if __name__ == "__main__" and __package__ is None:
    # This hack allows relative imports to work when running directly
    # We add the root directory to path, then explicitly import the module inside the 'src.app' package
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.append(root_dir)
    __package__ = "src.app"

from flask import Flask, request, render_template, send_file, redirect, url_for, flash, jsonify
import threading, json, asyncio, uuid, shutil, os
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
from ..utils.file_ops import (
    upload_single_file,
    upload_folder,
    download_from_discord,
    delete_from_discord,
    fetch_files_from_channel
)

load_dotenv()

# Calculate the path to the 'template' folder in the project root
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
template_dir = os.path.join(base_dir, 'templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = os.urandom(24) 

# bot token
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
@app.route('/upload', methods=['POST'])
def upload_handler():
    server_id = request.form.get('server_id')
    channel_name = request.form.get('channel')
    secure_upload = request.form.get('encrypt') == 'true'
    custom_folder_name = request.form.get('folder_name')
    files = request.files.getlist('files[]')

    if not all([server_id, channel_name, files]):
        return 'Missing form data', 400

    is_folder_upload = any('/' in f.filename for f in files if f.filename)

    if is_folder_upload:
        logger.info("Folder upload detected.")
        folder_tree = {}
        all_chunk_paths = []
        # Use custom folder name if provided, otherwise use directory from first file
        folder_name = custom_folder_name or os.path.dirname(files[0].filename) or "upload"

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
            "upload_type": "folder", 
            "folder_name": folder_name, 
            "encrypted": secure_upload,
            "total_size": sum(os.path.getsize(p) for p in all_chunk_paths), # calc size of all chunks
            "tree": folder_tree.get(folder_name, {}).get("children", folder_tree)
        }
        
        try:
            future = asyncio.run_coroutine_threadsafe(upload_folder(final_metadata, all_chunk_paths, server_id, channel_name), bot.loop)
            future.result()
        except Exception as e:
            logger.error(f"Error uploading folder '{folder_name}': {e}")
            # Clean up any remaining chunk files
            for chunk_path in all_chunk_paths:
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)
            return jsonify({"status": "error", "message": f"Folder upload failed: {str(e)}"}), 500
        
        return jsonify({"status": "success", "message": f"Folder '{folder_name}' uploaded."})

    else:
        logger.info("Individual file upload detected.")
        for file in files:
            if not file.filename: continue
            
            temp_file_path = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}")
            file.save(temp_file_path)

            try:
                future = asyncio.run_coroutine_threadsafe(
                    upload_single_file(temp_file_path, file.filename, server_id, channel_name, secure_upload),
                    bot.loop
                )
                future.result()
            except Exception as e:
                logger.error(f"Error uploading file '{file.filename}': {e}")
                # Ensure cleanup if upload fails
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            finally:
                # Final cleanup check for temp file
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
        return jsonify({"status": "success", "message": f"{len(files)} files uploaded."})



# --- File Listing Logic ---
@app.route('/list_files', methods=['POST'])
def list_files_route():
    data = request.get_json()
    server_id = data.get('server_id')
    channel_name = data.get('channel_name')
    
    if not server_id or not channel_name:
        return jsonify({"error": "Missing server_id or channel_name"}), 400

    future = asyncio.run_coroutine_threadsafe(fetch_files_from_channel(server_id, channel_name), bot.loop)
    files = future.result()
    
    return jsonify({"files": files})


# --- Download Logic ---
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

# --- Delete Logic ---
@app.route('/delete', methods=['POST'])
def delete_route():
    data = request.get_json()
    server_id = data.get('server_id')
    filename = data.get('filename')
    channel_name = data.get('channel_name')
    
    if not all([server_id, filename, channel_name]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400
    
    logger.info(f"Delete request for '{filename}' from server '{server_id}' in channel '{channel_name}'")
    
    try:
        future = asyncio.run_coroutine_threadsafe(delete_from_discord(server_id, channel_name, filename), bot.loop)
        success = future.result()
        
        if success:
            return jsonify({"status": "success", "message": f"Successfully deleted '{filename}'."})
        else:
            return jsonify({"status": "error", "message": f"Failed to delete '{filename}'."}), 400
    except Exception as e:
        logger.error(f"Error in delete route: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Main Execution ---
def run_flask():
    app.run(use_reloader=False, port=5000, host="0.0.0.0")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)