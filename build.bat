@echo off
setlocal

set URL=http://localhost:8080

docker compose version >nul 2>&1
if errorlevel 1 (
    echo This needs Docker Compose v2 ^(the "docker compose" subcommand^).
    exit /b 1
)

if "%1"=="--delete_db" (
    echo Deleting the database volume and stopping containers...
    docker compose down
    docker volume rm ai-webscraper_postgres_data
    echo Database volume deleted and containers stopped.
    exit /b
)

echo Building and starting containers...
if "%1"=="--build" (
    docker compose up --build -d
) else (
    echo Starting containers without rebuild...
    docker compose up -d
)

start %URL%

echo Done! The web interface is available at %URL%
echo Press any key to stop the containers...
pause

docker compose down
