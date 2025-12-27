import discord
import os
import json
import uuid
import asyncio
import shutil
from ..dis_commands import bot
from .util import logger, cipher, DATA_DIRECTORY, process_and_chunk_file

# --- Upload Operations ---
async def upload_single_file(file_path, original_filename, server_id, channel_name, secure):
    """Handles the upload process for a single file using the unified chunker."""
    guild = bot.get_guild(int(server_id))
    if not guild: return logger.error(f"Upload failed: Guild {server_id} not found.")
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return logger.error(f'Upload failed: Channel "{channel_name}" not found.')

    try:
        # Get original file size BEFORE processing (processing modifies/moves the file)
        original_size = os.path.getsize(file_path)
        
        # Use the unified helper for all processing and naming
        chunk_paths, chunk_basenames = process_and_chunk_file(file_path, secure)

        metadata = {
            "original_filename": original_filename,
            "original_size": original_size,
            "chunks": chunk_basenames,
            "encrypted": secure
        }
        metadata_filename = os.path.join(DATA_DIRECTORY, f"{uuid.uuid4()}_metadata.json")
        metadata_content = json.dumps(metadata).encode()
        if secure: metadata_content = cipher.encrypt(metadata_content)
        with open(metadata_filename, 'wb') as f: f.write(metadata_content)

        # Upload metadata using the filename base (strip original extension)
        metadata_attachment_name = f"{os.path.splitext(original_filename)[0]}_metadata.json"
        await channel.send(file=discord.File(metadata_filename, filename=metadata_attachment_name))
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


# --- Download Operations ---
async def download_from_discord(server_id, channel_name, requested_path):
    """Downloads a file or folder, with synchronized and robust error handling."""
    # Get guild and channel
    guild = bot.get_guild(int(server_id))
    if not guild: return logger.error(f"Download failed: Guild {server_id} not found.")
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return logger.error(f"Download failed: Channel '{channel_name}' not found.")

    # Get metadata
    root_object_name = requested_path.split('/')[0]
    # Use base name (strip extension) when searching for metadata attachments
    root_base = os.path.splitext(root_object_name)[0]
    metadata_filename_to_find = f"{root_base}_metadata.json"
    
    # Build file cache
    logger.info("Building file cache from channel history...")
    file_cache = {
        attachment.filename: message
        async for message in channel.history(limit=2000)
        for attachment in message.attachments
    }
    logger.info(f"Cache built with {len(file_cache)} files.")

    # Get metadata
    metadata_message = None
    
    # 1. Exact match attempt
    if metadata_filename_to_find in file_cache:
        metadata_message = file_cache[metadata_filename_to_find]
        logger.info(f"Metadata found via exact match: {metadata_filename_to_find}")
    
    # 2. Fallback: Try sanitized version (Discord replaces spaces with underscores)
    if not metadata_message:
        sanitized_name = metadata_filename_to_find.replace(' ', '_')
        if sanitized_name in file_cache:
            metadata_message = file_cache[sanitized_name]
            logger.info(f"Metadata found via sanitized match: {sanitized_name}")
            
    if not metadata_message: return logger.error(f"Metadata for '{root_object_name}' not found (checked '{metadata_filename_to_find}' and '{metadata_filename_to_find.replace(' ', '_')}').")

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


# --- Delete Operations ---
async def delete_from_discord(server_id, channel_name, file_name):
    """Deletes a file or folder and all associated chunks from Discord channel."""
    guild = bot.get_guild(int(server_id))
    if not guild: 
        logger.error(f"Delete failed: Guild {server_id} not found.")
        return False
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: 
        logger.error(f"Delete failed: Channel '{channel_name}' not found.")
        return False

    try:
        # Normalize target name for comparison
        # Remove trailing slash for consistency (folders might be passed as "folder/" or "folder")
        target_name = file_name.rstrip('/')
        
        logger.info(f"Initiating delete for '{target_name}'. Scanning metadata files...")
        
        filenames_to_delete = set()
        metadata_message = None
        metadata_filename_found = None
        
        # Scan all messages for metadata files
        # We need to read content to confirm it's the right file, as filenames might start with UUIDs 
        # or be renamed by Discord (spaces -> underscores)
        async for message in channel.history(limit=2000):
            for attachment in message.attachments:
                if attachment.filename.endswith('_metadata.json'):
                    try:
                        content = await attachment.read()
                        try:
                            metadata = json.loads(content)
                        except:
                            # Try decrypting if not valid JSON directly
                            try:
                                metadata = json.loads(cipher.decrypt(content))
                            except Exception:
                                # Not a valid encrypted file or wrong key, skip
                                continue
                        
                        # Check if this metadata matches our target
                        matched = False
                        
                        # Case 1: Folder
                        if metadata.get("upload_type") == "folder":
                            if metadata.get("folder_name") == target_name:
                                matched = True
                                logger.info(f"Found matching folder metadata: {attachment.filename}")
                        
                        # Case 2: Single File
                        else:
                            if metadata.get("original_filename") == target_name:
                                matched = True
                                logger.info(f"Found matching file metadata: {attachment.filename}")
                                
                        if matched:
                            metadata_message = message
                            metadata_filename_found = attachment.filename
                            
                            # Extract chunks to delete
                            if metadata.get("upload_type") == "folder":
                                # Recursively extract chunks from tree
                                def extract_chunks_from_tree(tree):
                                    chunks = []
                                    for name, item in tree.items():
                                        if item.get("type") == "file":
                                            chunks.extend(item.get("chunks", []))
                                        elif item.get("type") == "directory":
                                            chunks.extend(extract_chunks_from_tree(item.get("children", {})))
                                    return chunks
                                
                                chunks = extract_chunks_from_tree(metadata.get("tree", {}))
                                filenames_to_delete.update(chunks)
                            else:
                                # Single file
                                filenames_to_delete.update(metadata.get("chunks", []))
                            
                            break # Found our target, break inner loop
                            
                    except Exception as e:
                        logger.warning(f"Error processing metadata candidate {attachment.filename}: {e}")
                        continue
            
            if metadata_message:
                break # Found our target, break outer loop

        if not metadata_message:
            logger.warning(f"No metadata found for '{target_name}' after scanning channel.")
            return False
            
        # Collect all messages to delete (metadata + chunks)
        messages_to_delete = [metadata_message]
        
        async for message in channel.history(limit=2000):
            for attachment in message.attachments:
                if attachment.filename in filenames_to_delete:
                    messages_to_delete.append(message)
        
        logger.info(f"Found {len(messages_to_delete)} messages to delete for '{target_name}'")
        
        # Delete all related messages
        delete_count = 0
        for message in messages_to_delete:
            try:
                await message.delete()
                delete_count += 1
                await asyncio.sleep(0.5)  # Rate limiting
            except discord.errors.NotFound:
                pass
            except Exception as e:
                logger.error(f"Error deleting message {message.id}: {e}")
        
        logger.info(f"Successfully deleted '{target_name}'")
        return True

    except Exception as e:
        logger.error(f"An error occurred during delete for '{file_name}': {e}")
        return False

# --- Listing Operations ---
async def fetch_files_from_channel(server_id, channel_name):
    """Fetches and parses all metadata files from the channel to list available files."""
    guild = bot.get_guild(int(server_id))
    if not guild: return []
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel: return []

    files_list = []
    
    # We need to read messages to find metadata files
    # This might be slow for huge history, but we'll use the same limit as download
    async for message in channel.history(limit=2000):
        for attachment in message.attachments:
            if attachment.filename.endswith('_metadata.json'):
                try:
                    content = await attachment.read()
                    try:
                        # Try decrypting first if it might be encrypted
                        # But we don't know if it is encrypted until we read it or try
                        # The upload logic decides encryption.
                        # Metadata itself is encrypted if secure=True.
                        # Let's try to load as JSON first, if fail, try decrypt
                        metadata = json.loads(content)
                    except:
                        try:
                            metadata = json.loads(cipher.decrypt(content))
                        except Exception as e:
                            logger.error(f"Failed to parse metadata {attachment.filename}: {e}")
                            continue

                    # Add timestamp from message
                    metadata['upload_date'] = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    metadata['message_id'] = message.id
                    files_list.append(metadata)
                except Exception as e:
                    logger.error(f"Error reading attachment {attachment.filename}: {e}")

    return files_list
