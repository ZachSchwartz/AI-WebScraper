@echo off
setlocal

:: Get URL and keyword from arguments, or use defaults
set "URL=%~1"
if "%URL%"=="" set "URL=https://example.com"

set "KEYWORD=%~2"
if "%KEYWORD%"=="" set "KEYWORD=python"

:: Build and start services in one go
echo 🚀 Starting services...
docker compose up -d --build --no-deps redis llm

:: Run scraper and display results in parallel
echo 🕷️ Running scraper and processing...
echo URL: %URL%
echo Keyword: %KEYWORD%
start /B cmd /c "docker compose run --rm producer python src/main.py --url "%URL%" --keyword "%KEYWORD%""
start /B cmd /c "timeout /t 3 /nobreak && docker compose exec llm python src/main.py --read-only"

:: Optional: Uncomment to stop containers after processing
:: echo 🛑 Stopping containers...
:: docker compose down

endlocal 