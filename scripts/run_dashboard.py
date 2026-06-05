#!/usr/bin/env python3
"""Start the Mantle Alpha dashboard server."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.app import start_server

if __name__ == "__main__":
    start_server()
