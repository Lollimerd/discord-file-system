import sys
import os
print(f"sys.path: {sys.path}")
try:
    from dis_commands import bot
    print("Successfully imported bot from dis_commands")
except ImportError as e:
    print(f"Failed to import bot: {e}")

try:
    from utils.util import logger
    print("Successfully imported logger from utils.util")
except ImportError as e:
    print(f"Failed to import logger: {e}")
