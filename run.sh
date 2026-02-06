#!/bin/bash
# Launch PyEnvy
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/.venv/bin/python3" "$DIR/pyenvy.py" "$@"
