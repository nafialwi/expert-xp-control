#!/bin/bash
set -e

echo "=== Expert Workstation Installer ==="

echo "Checking dependencies..."
missing=()
command -v python3 >/dev/null || missing+=("python")
command -v node >/dev/null || missing+=("nodejs")
command -v git >/dev/null || missing+=("git")

if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing: ${missing[*]}"
    echo "Install with: pkg install ${missing[*]}"
    exit 1
fi
echo "Dependencies OK"

XP_HOME="$HOME/.expert-workstation"
mkdir -p "$XP_HOME/versions" "$XP_HOME/runs" "$XP_HOME/checkpoints" "$XP_HOME/config"

REPO_URL="https://github.com/nafialwi/expert-xp-control.git"
CLONE_PATH="$XP_HOME/engine"
if [ -d "$CLONE_PATH" ]; then
    cd "$CLONE_PATH" && git fetch origin xp-engine && git checkout xp-engine && git pull
else
    git clone --branch xp-engine --single-branch "$REPO_URL" "$CLONE_PATH"
fi

VERSION="2.0.0-rc15"
mkdir -p "$XP_HOME/versions/$VERSION/src"
cp -r "$CLONE_PATH/src/xp" "$XP_HOME/versions/$VERSION/src/"
echo "$VERSION" > "$XP_HOME/active-version"

DEVICE_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex)")
cat > "$XP_HOME/config/workstation.json" << JSONCFG
{
  "device_id": "$DEVICE_ID",
  "control_repo": null,
  "projects": []
}
JSONCFG

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/xp" << 'XPWRAP'
#!/bin/bash
VERSION=$(cat ~/.expert-workstation/active-version)
PYTHONPATH="$HOME/.expert-workstation/versions/$VERSION/src" python3 -m xp.cli "$@"
XPWRAP
chmod +x "$HOME/.local/bin/xp"

if ! grep -q '.local/bin' "$HOME/.bashrc"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi

echo ""
echo "=== Installation Complete ==="
echo "Run: source ~/.bashrc"
echo "Then: xp help"
