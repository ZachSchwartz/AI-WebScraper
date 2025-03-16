@echo off
setlocal

:: Get URL and keyword from arguments, or use defaults
set "URL=%~1"
if "%URL%"=="" set "URL=https://example.com"

set "KEYWORD=%~2"
if "%KEYWORD%"=="" set "KEYWORD=python"

:: Check if build is needed
set "BUILD="
if "%3"=="--build" set "BUILD=--build"

:: Start services (only build if explicitly requested)
echo 🚀 Starting services...
docker compose up -d --no-deps %BUILD% redis llm

:: Run scraper and display results in parallel
echo 🕷️ Running scraper and processing...
echo URL: %URL%
echo Keyword: %KEYWORD%
docker compose run --rm -e URL="%URL%" -e KEYWORD="%KEYWORD%" producer
start /B cmd /c "timeout /t 20 /nobreak && docker compose exec llm python src/main.py --read-only"

endlocal