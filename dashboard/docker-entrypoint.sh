#!/usr/bin/env sh
# dashboard/docker-entrypoint.sh
# Substitutes ${INTERNAL_KEY} in the nginx config template at container startup,
# then launches nginx. The key is read from the environment and never stored
# in the image layer.
set -e

TEMPLATE=/etc/nginx/templates/dashboard.conf.template
OUTPUT=/etc/nginx/conf.d/dashboard.conf

if [ -z "${INTERNAL_KEY:-}" ]; then
  echo "[dashboard] WARNING: INTERNAL_KEY is not set — write API calls will fail auth" >&2
fi

# envsubst replaces ${INTERNAL_KEY} in the template
envsubst '${INTERNAL_KEY}' < "$TEMPLATE" > "$OUTPUT"

echo "[dashboard] nginx config generated (key length=${#INTERNAL_KEY})"
exec nginx -g "daemon off;"
