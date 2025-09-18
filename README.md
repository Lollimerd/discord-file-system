# Discord Cloud Storage Documentation

## Project Overview

Discord Cloud Storage is a Flask-based web application that utilizes Discord as a file storage backend. The system allows users to upload files through a web interface, which are then chunked (if necessary) and stored in a Discord channel as attachments. The application also supports downloading previously uploaded files by reassembling the chunks.

The project includes two versions:
1. **Standard Version** `discord_cloud_no_enc.py` - Basic functionality without encryption
2. **Secure Version** `secure_cloud.py` - Enhanced security with file encryption using Fernet

## System Architecture

### Components

1. **Web Interface** - Flask-based frontend for file upload/download
2. **Discord Bot** - Backend for storing and retrieving files from Discord channels
3. **File Processing Engine** - Handles chunking, metadata management, and file reassembly
4. **Encryption Module** (Secure version only) - Handles file encryption/decryption

### Data Flow

#### Upload Process:
- 1. User uploads a file via the web interface
- 2. System checks if the file exceeds Discord's file size limit (25MB)
- 3. If needed, the file is split into chunks
- 4. File is encrypted before storage **(For Encrypted version)**
- 5. Metadata is created to track file chunks
- 6. The Discord bot uploads the metadata and file chunks to the specified channel

#### Download Process:
- 1. User selects a file and channel for download
- 2. System retrieves the metadata from Discord
- 3. Each chunk is downloaded and reassembled
- 4. (Secure version) The file is decrypted
- 5. The complete file is served to the user

## Setup and Configuration

### Requirements
- `Python 3.6+`
- `Flask`
- `Discord.py`
- `Cryptography (for secure version)`
- `Discord bot token`

### Environment Variables
- `bot_token`: Discord bot token for authentication
- `enc_key`: Encryption key (secure version only)

### Directory Structure
```
discord-cloud-storage/
├── discord_cloud_no_enc.py  # Standard version without encryption
├── secure_cloud.py          # Secure version with encryption
├── dis_commands.py          # Discord bot commands
├── Data/                    # Temporary file storage directory
└── templates/               # Flask HTML templates
   ├── index.html           # Main page with upload/download forms
   └── uploaded.html        # Confirmation page after upload
```

## Technical Details
### File Chunking

Files larger than 25MB (Discord's file size limit) are split into smaller chunks:

```python
chunk_size = 25 * 1024 * 1024  # 25 MB
```

Each chunk is named using the pattern: `{filename}_part_{chunk_number}.{extension}`

### Metadata

For each uploaded file, a metadata JSON file is created to track:
- Original filename
- File size (for large files)
- Number of chunks
- List of chunk filenames
- (Secure version) Encryption key

```python
# normal
metadata = {
"original_filename": filename,
"file_size": filesize,
"no of chunks": chunk_num,
"chunks": chunks
}

# encrypted
metadata = {
"original_filename": filename,
"chunks": [os.path.basename(chunk) for chunk in chunks],
"encryption key": encryption_key.decode()
}
```
### Writing metadata to file
How to write the metadata file in json format, deletes local copy after upload as saved in discord server. When downloading, it finds the **metadata file** associated with a `specified file` that you searched. 
```python
metadata_filename = os.path.join(DATA_DIRECTORY, f"{file_base}_metadata.json")
with open(metadata_filename, 'w') as metadata_file:
json.dump(metadata, metadata_file)
```

### Security Features (Secure Version)

The secure version implements Fernet symmetric encryption:
- Files are encrypted before uploading to Discord
- Metadata is also encrypted
- The encryption key is stored in the metadata
- Files are automatically decrypted upon download

```python
# Encryption setup
encryption_key = os.getenv("enc_key").encode()
cipher = Fernet(encryption_key)
```

### Logging

The system uses colorlog for enhanced console output with different colors for:
- DEBUG (bold cyan)
- INFO (bold green)
- WARNING (bold yellow)
- ERROR (red)
- CRITICAL (bold red)

## API Reference

### Web Endpoints

#### GET /
- Returns the main page with upload/download interface

#### POST /upload
- Parameters:
- `file`: The file to upload
- `channel`: The Discord channel name for storage
- Returns: Confirmation page or error message

#### POST /download
- Parameters:
- `channels`: The Discord channel name where the file is stored
- `files`: The filename to download
- Returns: The downloaded file or error message

### Discord Bot Functions

#### on_ready()
- Triggered when the bot connects to Discord
- Logs the successful connection

#### upload_to_discord(file_path, filename, channel_name)
- Uploads a file to the specified Discord channel
- Handles chunking for large files
- Creates and uploads metadata

#### download_files(channel_name, filename)
- Downloads file chunks from Discord
- Reassembles the original file
- (Secure version) Decrypts the file

#### The project also includes several discord bot commands (defined in `dis_commands.py`)

```python
@bot.command(name='channel_info')
async def channel_info(ctx, channel_id: int):
# Get channel information

@bot.command(name='get_members')
async def get_members(ctx):
# List guild members

@bot.command(name='check_attachments')
async def check_attachments(ctx):
# List attachments in a channel

@bot.command(name='ping')
async def ping(ctx):
# Simple ping command for testing
```

## Error Handling

The system includes error handling for common scenarios:
- Channel not found
- File not found
- Metadata not found
- Chunking/reassembly failures
- **(Secure version)** Encryption/decryption failures

## Limitations and Considerations

1. **Discord Rate Limits**: Be aware of Discord's API rate limits when uploading/downloading large files or numerous chunks.

2. **File Size**: While the system can handle files larger than 25MB through chunking, there are practical limits to file size due to Discord's message history limitations.

3. **Security** (Standard version): The non-encrypted version does not provide security for sensitive files. Use the secure version for confidential data.

4. **Key Management** (Secure version): The encryption key is stored in the metadata file. While this metadata is itself encrypted, a more robust key management system might be desirable for highly sensitive applications.

5. **Channel History Limit**: Discord has limits on message history, which may affect retrieval of older files.

## Future Enhancements

Potential improvements for the system:
- User authentication
- File sharing capabilities 
- Improved error recovery
- Progress indicators for large file transfers
- Enhanced key management
- Compression before chunking
- multiple files of upload & downloading process
- improve encryption/decryption capabilities