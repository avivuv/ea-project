import sys
from pathlib import Path

# backend/ ke sys.path supaya `import tg_signal` dan modul lama (config, fvg_detector) bisa diimport
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
