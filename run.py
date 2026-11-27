#!/usr/bin/env python3
"""Launch the Daily Playlist Player server.

Same as: python3 server/app.py
See README.md for options (--port, --db, --refresh-today, --reseed).
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "server")
)

import app

if __name__ == "__main__":
    app.main()
