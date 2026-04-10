#!/bin/bash
# Docker/Podman entrypoint: bootstrap config files into the mounted volume, then run hermes.
set -e

HERMES_HOME="${HERMES_HOME:-/opt/data}"
INSTALL_DIR="/opt/hermes"

# --- Privilege dropping via gosu ---
# When started as root (the default for Docker, or fakeroot in rootless Podman),
# optionally remap the hermes user/group to match host-side ownership, fix volume
# permissions, then re-exec as hermes.
if [ "$(id -u)" = "0" ]; then
    if [ -n "$HERMES_UID" ] && [ "$HERMES_UID" != "$(id -u hermes)" ]; then
        echo "Changing hermes UID to $HERMES_UID"
        usermod -u "$HERMES_UID" hermes
    fi

    if [ -n "$HERMES_GID" ] && [ "$HERMES_GID" != "$(id -g hermes)" ]; then
        echo "Changing hermes GID to $HERMES_GID"
        # -o allows non-unique GID (e.g. macOS GID 20 "staff" may already exist
        # as "dialout" in the Debian-based container image)
        groupmod -o -g "$HERMES_GID" hermes 2>/dev/null || true
    fi

    actual_hermes_uid=$(id -u hermes)
    if [ "$(stat -c %u "$HERMES_HOME" 2>/dev/null)" != "$actual_hermes_uid" ]; then
        echo "$HERMES_HOME is not owned by $actual_hermes_uid, fixing"
        # In rootless Podman the container's "root" is mapped to an unprivileged
        # host UID — chown will fail.  That's fine: the volume is already owned
        # by the mapped user on the host side.
        chown -R hermes:hermes "$HERMES_HOME" 2>/dev/null || \
            echo "Warning: chown failed (rootless container?) — continuing anyway"
    fi

    echo "Dropping root privileges"
    exec gosu hermes "$0" "$@"
fi

# --- Running as hermes from here ---
source "${INSTALL_DIR}/.venv/bin/activate"

# Create essential directory structure.  Cache and platform directories
# (cache/images, cache/audio, platforms/whatsapp, etc.) are created on
# demand by the application — don't pre-create them here so new installs
# get the consolidated layout from get_hermes_dir().
# The "home/" subdirectory is a per-profile HOME for subprocesses (git,
# ssh, gh, npm …).  Without it those tools write to /root which is
# ephemeral and shared across profiles.  See issue #4426.
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# Ensure ~/.hermes symlinks to the persistent volume so that Hermes
# resolves its data directory regardless of how it discovers $HOME.
# The container filesystem is ephemeral — this must run every boot.
HERMES_LINK="$HOME/.hermes"
if [ ! -e "$HERMES_LINK" ]; then
    ln -s "$HERMES_HOME" "$HERMES_LINK"
fi

# Ensure ~/.honcho config survives rebuilds by symlinking from the volume.
# The entrypoint creates a minimal config if one doesn't exist yet;
# the API key is read from $HERMES_HOME/.env (HONCHO_API_KEY).
HONCHO_DIR="$HERMES_HOME/.honcho"
mkdir -p "$HONCHO_DIR"
if [ ! -f "$HONCHO_DIR/config.json" ]; then
    echo '{"enabled": true}' > "$HONCHO_DIR/config.json"
fi
if [ ! -e "$HOME/.honcho" ]; then
    ln -s "$HONCHO_DIR" "$HOME/.honcho"
fi

# .env
if [ ! -f "$HERMES_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env"
fi

# config.yaml
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml"
fi

# SOUL.md
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$HERMES_HOME/SOUL.md"
fi

# Sync bundled skills (manifest-based so user edits are preserved)
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py"
fi

# Lane 1: Clone/update FirmVault for the case pipeline engine.
# The vault lives on the persistent volume so case state survives rebuilds.
FIRMVAULT_DIR="$HERMES_HOME/firmvault"
if [ ! -d "$FIRMVAULT_DIR/.git" ]; then
    echo "entrypoint: cloning FirmVault..."
    git clone https://github.com/Whaleylaw/FirmVault.git "$FIRMVAULT_DIR" 2>&1 | tail -1
else
    echo "entrypoint: updating FirmVault..."
    git -C "$FIRMVAULT_DIR" pull --ff-only origin main 2>&1 | tail -1 || true
fi

# Lane 2: Clone/update GSD library for ad-hoc projects.
GSD_DIR="$HERMES_HOME/gsd-lawyerinc"
if [ ! -d "$GSD_DIR/.git" ]; then
    echo "entrypoint: cloning GSD..."
    git clone https://github.com/Whaleylaw/gsd-lawyerinc.git "$GSD_DIR" 2>&1 | tail -1
else
    echo "entrypoint: updating GSD..."
    git -C "$GSD_DIR" pull --ff-only origin main 2>&1 | tail -1 || true
fi

# Ensure projects directory exists for GSD ad-hoc projects
mkdir -p "$HERMES_HOME/projects"

exec hermes "$@"
