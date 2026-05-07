#!/bin/bash
# WOA AutoBot macOS launcher script
# This script is placed inside the .app bundle and properly resolves paths

DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES="$DIR/../Resources"
INTERNAL="$DIR/../Resources/_internal"

# Set _MEIPASS for PyInstaller compatibility
export _MEIPASS2="$RESOURCES"

# Execute the real binary
exec "$DIR/WOA_AutoBot" "$@"
