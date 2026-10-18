import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["DEADAIR_SAVE_DIR"] = tempfile.mkdtemp(prefix="deadair_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
