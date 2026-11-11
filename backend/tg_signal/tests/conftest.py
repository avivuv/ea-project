import sys
from pathlib import Path

# backend/ ke sys.path supaya `import tg_signal` bisa diimport
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
