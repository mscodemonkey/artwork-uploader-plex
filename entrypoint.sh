#!/bin/bash
set -e

# Default PUID and PGID to 1000 if not set
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "Starting with PUID=$PUID and PGID=$PGID"

# Execute the command as the specified user (using numeric UID:GID)
exec gosu ${PUID}:${PGID} "$@"
