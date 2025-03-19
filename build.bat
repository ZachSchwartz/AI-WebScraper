@echo off
echo Building and starting containers...

REM Check if --build argument is provided
if "%1"=="--build" (
    echo Rebuilding containers...
    docker-compose up --build -d
) else (
    echo Starting containers without rebuild...
    docker-compose up -d
)

REM Wait for services to be ready
echo Waiting for services to be ready...
timeout /t 10

REM Open the web interface in the default browser
start http://localhost:8080

echo Done! The web interface is available at http://localhost:8080
echo Press any key to stop the containers...
pause

REM Stop the containers
docker-compose down