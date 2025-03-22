@echo off
echo Building and starting containers...

REM Check if --delete_db argument is provided
if "%1"=="--delete_db" (
    echo Deleting the database volume and stopping containers...
    docker-compose down
    docker volume rm ai-webscraper_postgres_data
    echo Database volume deleted and containers stopped.
    exit /b
)

REM Check if --build argument is provided
if "%1"=="--build" (
    echo Rebuilding containers...
    docker-compose up --build -d
) else (
    echo Starting containers without rebuild...
    docker-compose up -d
)

REM Open the web interface in the default browser
start http://localhost:8080

echo Done! The web interface is available at http://localhost:8080
echo Press any key to stop the containers...
pause

REM Stop the containers
docker-compose down