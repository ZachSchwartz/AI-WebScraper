#!/usr/bin/env bash
echo "Building and starting containers..."

if [ "$1" = "--delete_db" ]; then
    echo "Deleting the database volume and stopping containers..."
    docker-compose down
    docker volume rm ai-webscraper_postgres_data
    echo "Database volume deleted and containers stopped."
    exit 0
fi

if [ "$1" = "--build" ]; then
    echo "Rebuilding containers..."
    docker-compose up --build -d
else
    echo "Starting containers without rebuild..."
    docker-compose up -d
fi

open http://localhost:8080

echo "Done! The web interface is available at http://localhost:8080"
read -n 1 -s -r -p "Press any key to stop the containers..."
echo

docker-compose down
