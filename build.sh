#!/usr/bin/env bash
set -euo pipefail

URL=http://localhost:8080

if ! docker compose version >/dev/null 2>&1; then
    echo "This needs Docker Compose v2 (the 'docker compose' subcommand)." >&2
    exit 1
fi

if [ "${1:-}" = "--delete_db" ]; then
    echo "Deleting the database volume and stopping containers..."
    docker compose down
    docker volume rm ai-webscraper_postgres_data 2>/dev/null ||
        echo "No database volume to delete."
    echo "Database volume deleted and containers stopped."
    exit 0
fi

echo "Building and starting containers..."
if [ "${1:-}" = "--build" ]; then
    docker compose up --build -d
else
    echo "Starting containers without rebuild..."
    docker compose up -d
fi

# Opening a browser is a convenience, so a machine without one is not an error.
if command -v open >/dev/null 2>&1; then
    open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"
fi

echo "Done! The web interface is available at $URL"
read -n 1 -s -r -p "Press any key to stop the containers..."
echo

docker compose down
