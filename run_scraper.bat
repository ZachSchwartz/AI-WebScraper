@echo off
setlocal

:: Get URL and keyword from arguments, or use defaults
set "URL=%~1"
if "%URL%"=="" set "URL=https://example.com"

set "KEYWORD=%~2"
if "%KEYWORD%"=="" set "KEYWORD=python"

echo 🔨 Building containers...
docker compose build --no-cache

echo 🚀 Starting Redis...
docker compose up -d redis

echo 🕷️ Running scraper...
echo URL: %URL%
echo Keyword: %KEYWORD%
docker compose run producer python src/main.py --url "%URL%" --keyword "%KEYWORD%"

:: Optional: Uncomment to stop Redis after scraping
:: echo 🛑 Stopping Redis...
:: docker compose down

endlocal 