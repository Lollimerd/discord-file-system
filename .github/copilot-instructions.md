# Discord File System - AI Coding Agent Instructions

## Project Overview

A Flask-based cloud storage system that leverages Discord as the backend storage. Files are uploaded to Discord channels via a bot, with automatic chunking (10MB default), optional AES encryption, and metadata tracking for reassembly.

**Key Architecture**: Flask web UI (threads) + Discord.py bot running in parallel via `threading` and `asyncio.run_coroutine_threadsafe()`.

## Critical Patterns & Architecture

### 1. **Async-Sync Bridge Pattern**
- Flask routes run in main thread, Discord bot runs in separate asyncio event loop
- **Always use**: `asyncio.run_coroutine_threadsafe(async_function(), bot.loop)` to call async operations from Flask
- Store result with `.result()`: `future.result()` (blocking, safe from Flask context)
- Example in `src/app/main.py`:
  ```python
  future = asyncio.run_coroutine_threadsafe(find_guild_by_name(server_name), bot.loop)
  server_id = future.result()
  ```

### 2. **File Chunking & Naming Convention**
- All files chunked via `process_and_chunk_file()` in `src/utils/util.py`
- **Single files**: Named `{base}_part_0{ext}` (not `_part_1`, always starts at 0)
- **Large files**: Named `{base}_part_0{ext}`, `{base}_part_1{ext}`, etc.
- Encryption happens **in-place** before chunking if `secure=True`
- Returns tuple: `(list_of_chunk_paths, list_of_chunk_basenames)`

### 3. **Metadata Structure**
- **Single file**:
  ```json
  {"original_filename": "...", "original_size": 12345, "chunks": ["file_part_0.ext"], "encrypted": false}
  ```
- **Folder**:
  ```json
  {"upload_type": "folder", "folder_name": "...", "encrypted": false, "total_size": 99999, "tree": {...}}
  ```
- **Tree format**: `{"filename": {"type": "file", "chunks": [...]}, "dirname": {"type": "directory", "children": {...}}}`
- Metadata is **encrypted if secure=True**, uploaded as `{name}_metadata.json`

### 4. **Data Flow: Upload**
1. Frontend sends files via `/upload` route
2. Detect folder vs. individual: check for `/` in filenames
3. **Single file**: `upload_single_file()` → chunk → upload metadata → upload chunks → cleanup
4. **Folder**: Build nested `folder_tree` dict → `upload_folder()` → upload metadata → upload all chunks in sequence
5. **Throttle**: 1.5s delay between Discord sends to avoid rate limits

### 5. **Data Flow: Download**
1. Request goes to `/download` with `filename`, `server_id`, `channel_name`
2. `download_from_discord()` builds file cache: `{attachment.filename: message_object}`
3. Find metadata file (`{root_name}_metadata.json`)
4. If folder + specific file path: navigate tree, reassemble single file
5. If folder + no path: build entire folder structure recursively, return ZIP
6. If single file: iterate chunks in order, reassemble, decrypt if needed
7. Serve file with `send_file()`

## Project Structure

```
src/
  app/main.py           # Flask routes (upload/download/list), upload_folder/single_file logic
  dis_commands.py       # Discord bot setup, commands (ping, channel_info, get_members, check_attachments)
  utils/util.py         # Utilities: encryption (Fernet), chunking, guild/channel fetching, logging
  templates/            # HTML (index.html, main.html, uploaded.html)
Data/                   # Temporary storage for chunks before upload
pyproject.toml          # Dependencies (Python 3.13+)
run.py                  # Entry point: starts Flask thread + bot
```

## Critical Dependencies & Configuration

- **Discord.py v2.6.4**: Bot with intents `message_content=True`, `members=True`
- **Flask 3.1.2**: Web framework, templates use `render_template()`
- **Cryptography (Fernet)**: AES encryption, **requires `enc_key` env var** (must be valid Fernet key)
- **Colorlog**: Colored logging output
- **Environment vars** (`.env`):
  - `bot_token`: Discord bot token (required)
  - `enc_key`: Base64-encoded Fernet key (required, generate with `Fernet.generate_key()`)

## Deployment & Running

- **Local**: `python run.py` (starts Flask on 0.0.0.0:5000 + bot)
- **Docker**: `docker compose up` (uses Dockerfile with Python 3.13)
- **Port**: Flask runs on 5000, Discord bot runs in event loop

## Common Workflows for AI Agents

### Adding Features
- **New Flask route**: Import from utils, use `asyncio.run_coroutine_threadsafe()` for bot calls
- **New Discord command**: Add to `src/dis_commands.py`, use `@bot.command()`
- **Utility functions**: Add to `src/utils/util.py`, keep encryption/chunking logic centralized

### Debugging
- Check logs: `colorlog` shows DEBUG/INFO/ERROR with colors
- Verify bot intents in `dis_commands.py`: must have `message_content=True` for message history
- Test chunking: `process_and_chunk_file()` returns paths—verify they exist before cleanup
- Metadata encryption: Try JSON parse first, fallback to `cipher.decrypt()`

### Refactoring
- **File handling**: Centralized in `process_and_chunk_file()` and `_build_folder_from_tree()`
- **Discord access**: All async operations must use bot reference from `dis_commands.bot`
- **Error handling**: Use `logger.error()` for consistency, cleanup files in `finally` blocks
