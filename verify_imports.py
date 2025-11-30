import sys
import os

# Ensure the current directory is in sys.path (it usually is by default)
if os.getcwd() not in sys.path:
    sys.path.append(os.getcwd())

print(f"sys.path: {sys.path}")

try:
    print("Attempting to import src.app.main...")
    from src.app import main
    print("Successfully imported src.app.main")
except ImportError as e:
    print(f"Failed to import src.app.main: {e}")
except Exception as e:
    print(f"An error occurred during import of src.app.main: {e}")

try:
    print("Attempting to import src.utils.util...")
    from src.utils import util
    print("Successfully imported src.utils.util")
except ImportError as e:
    print(f"Failed to import src.utils.util: {e}")
except Exception as e:
    print(f"An error occurred during import of src.utils.util: {e}")
