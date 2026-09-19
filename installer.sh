#!/usr/bin/env sh
# XP_PLUS_INSTALLER_WRAPPER_V1
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALLER="$SCRIPT_DIR/install.py"
if [ ! -f "$INSTALLER" ]; then
    echo "XP+ install.py is missing; use the complete release source/archive." >&2
    false
fi
exec python "$INSTALLER" "$@"
