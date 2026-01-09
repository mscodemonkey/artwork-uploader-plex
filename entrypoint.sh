#!/bin/bash
set -e

# Default PUID and PGID to 1000 if not set
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "Starting with PUID=$PUID and PGID=$PGID"

# Check if artwork group exists, if not create it
if ! getent group artwork > /dev/null 2>&1; then
    groupadd -g ${PGID} artwork
else
    # Update the group ID if it exists but has a different ID
    CURRENT_PGID=$(getent group artwork | cut -d: -f3)
    if [ "$CURRENT_PGID" != "$PGID" ]; then
        groupmod -g ${PGID} artwork
    fi
fi

# Check if artwork user exists, if not create it
if ! id artwork > /dev/null 2>&1; then
    useradd -u ${PUID} -g ${PGID} -m -s /bin/bash artwork
else
    # Update the user ID if it exists but has a different ID
    CURRENT_PUID=$(id -u artwork)
    if [ "$CURRENT_PUID" != "$PUID" ]; then
        usermod -u ${PUID} artwork
    fi
    # Ensure user is in the correct group
    usermod -g ${PGID} artwork
fi

# Ensure the artwork user owns necessary directories
chown -R artwork:artwork /app /logs /bulk_imports 2>/dev/null || true

# Execute the command as the artwork user
exec gosu artwork "$@"
