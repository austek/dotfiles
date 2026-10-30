"""Entry point for `mise run pin`; the logic is dotfiles_setup.pin_checksums."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from dotfiles_setup.pin_checksums import main

if __name__ == "__main__":
    sys.exit(main())
