import sys
import os
import threading

# Ensure the project root is in python path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.append(root_dir)

# Import main as a module relative to src package
from src.app import main

if __name__ == "__main__":
    print("Starting Discord File System...")
    # Run Flask in a separate thread
    flask_thread = threading.Thread(target=main.run_flask, daemon=True)
    flask_thread.start()
    
    # Run Discord Bot
    print("Bot is starting...")
    main.bot.run(main.TOKEN)
