# Discord Cloud Storage

[](https://www.python.org/)
[](https://flask.palletsprojects.com/)
[](https://discordpy.readthedocs.io/en/latest/)

A powerful and easy-to-use application that transforms a private Discord server into a personal, private, and encrypted cloud storage solution, accessible through a clean web interface.

## Overview

This project leverages the unlimited file storage of Discord by providing a Flask-based web UI to upload, download, and manage your files. It uses a Discord bot to handle the backend operations within a designated server. Files are split into configurable chunks (defaulting to 10MB), optionally encrypted, and uploaded to a text channel. A metadata file is generated for each upload, allowing the system to reassemble and decrypt the files upon download.

-----

## ✨ Key Features

  * **🌐 Web Interface:** A modern, user-friendly dashboard built with Flask and Tailwind CSS to manage your files. No complex commands needed for core operations.
  * **📁 File & Folder Uploads:** Drag-and-drop or select entire folders to upload. The original directory structure is preserved.
  * **🧩 File Chunking:** Large files are automatically split into smaller chunks to comply with Discord's file size limits, enabling the storage of files of virtually any size.
  * **🔒 Optional Encryption:** End-to-end AES encryption for both files and their metadata using the `cryptography` library. Your data remains private and unreadable to anyone without the key.
  * **📦 Metadata Management:** Each file or folder upload is accompanied by a `_metadata.json` file, which tracks all the necessary information for reassembly, including chunk names, original filenames, and encryption status.
  * **🤖 Diagnostic Bot Commands:** Includes slash commands for server administrators to get information about channels, members, and attachments directly within Discord.

-----

## ⚙️ How It Works

The application runs a Flask web server and a Discord bot in parallel using threading.

1.  **Upload Process:**

      * You select a file or folder through the web UI.
      * The Flask backend receives the files.
      * Each file is processed:
          * If encryption is enabled, the file is encrypted in memory.
          * The file is split into chunks (e.g., 10MB each). Single-chunk files are also named following the chunking convention for consistency (`_part_0`).
      * A metadata JSON file is created, mapping the original filename/folder structure to its corresponding chunk names.
      * The bot uploads the metadata file to the selected Discord channel, followed by each individual file chunk.
      * Temporary files are cleaned up from the server.

2.  **Download Process:**

      * You request a file or folder by its original name in the web UI.
      * The bot searches the specified channel for the corresponding `_metadata.json` file.
      * It reads the metadata to identify all the required chunks.
      * It downloads each chunk in order and reassembles them into a single file.
      * If the file was encrypted, it is decrypted using your secret key.
      * The final, reassembled file is served to you for download.

-----

## 🚀 Setup and Installation

### Prerequisites

  * **Python 3.8+**
  * A **Discord Bot Token**. You can create a bot and get a token from the [Discord Developer Portal](https://www.google.com/search?q=https://discord.com/developers/applications).
      * Your bot needs the **Privileged Gateway Intents** enabled:
          * `SERVER MEMBERS INTENT`
          * `MESSAGE CONTENT INTENT`
  * Invite the bot to your Discord server with `Administrator` permissions.

### 1\. Clone the Repository

```bash
git clone <your-repo-url>
cd <repository-folder>
```

### 2\. Create a Virtual Environment

It's highly recommended to use a virtual environment to manage dependencies.

```bash
# For Windows
python -m venv venv
.\venv\Scripts\activate

# For macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3\. Install Dependencies

Create a `requirements.txt` file with the following content:

```txt
flask
discord.py
python-dotenv
cryptography
colorlog
```

Then, install them using pip:

```bash
pip install -r requirements.txt
```

### 4\. Configure Environment Variables

Create a file named `.env` in the root directory of the project. This file will store your sensitive credentials.

```env
bot_token="YOUR_DISCORD_BOT_TOKEN_HERE"
enc_key="YOUR_SECRET_ENCRYPTION_KEY_HERE"
```

  * `bot_token`: Your bot token from the Discord Developer Portal.

  * `enc_key`: A 32-byte secret key for encryption. You can generate a new one by running the following Python script:

    ```python
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    print(key.decode())
    ```

    **Important:** Keep this key safe\! If you lose it, you will not be able to decrypt your files.

### 5\. Run the Application

Once everything is configured, start the application:

```bash
python -m src.app.main
```

The Flask server will be accessible at `http://127.0.0.1:5000` by default.

-----

## 📖 Usage Guide

1.  **Access the Web UI:** Open your browser and navigate to `http://127.0.0.1:5000`.
2.  **Select Your Server:** Enter the **exact name** of the Discord server your bot is in and click **Continue**.
3.  **Uploading Files:**
      * Use the **Select Files** or **Select Folder** buttons to choose what you want to upload.
      * Selected files will appear in the **Staging Area**.
      * Choose the **Target Channel** from the dropdown menu.
      * Check the **Encrypt files?** box if you want your files to be encrypted.
      * Click **Upload**.
4.  **Downloading Files:**
      * In the "Download File" card, enter the **exact original name** of the file or folder you want to download (e.g., `MyDocument.pdf` or `MyProjectFolder`).
      * If you are downloading a specific file from within an uploaded folder, use its relative path (e.g., `MyProjectFolder/src/main.js`).
      * Select the **Source Channel** where the file was originally uploaded.
      * Click **Download**. The application will find the parts, reassemble them, and prompt you to save the file.

-----

## 🤖 Discord Bot Commands

These commands can be used directly in your Discord server for diagnostics and information gathering.

  * `!ping`
      * Checks the bot's latency. Responds with "Pong\!".
  * `!channel_info [channel_id]`
      * Provides detailed information about a specific text channel.
  * `!get_members`
      * Lists all members in the current server.
  * `!check_attachments`
      * Scans the recent history of the current channel and lists information about any attachments found.

-----

## 📂 Project Structure

```
.
├── Data/                 # Temporary directory for file processing (auto-generated)
├── src/
│   ├── app/
│   │   └── main.py       # Core Flask and Discord bot logic
│   ├── utils/
│   │   └── util.py       # Helper functions and logger configuration
│   ├── templates/
│   │   ├── index.html    # Server selection page
│   │   ├── main.html     # Main dashboard for upload/download
│   │   └── uploaded.html # Success confirmation page
│   ├── dis_commands.py   # Defines the Discord bot's '!' commands
│   └── __init__.py
├── .env                  # Environment variables (bot token, encryption key)
├── requirements.txt      # Python dependencies
├── Dockerfile
└── compose.yaml
```