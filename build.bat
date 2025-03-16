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

:: Start Redis only
echo 🚀 Starting Redis...
docker compose up -d --no-deps %BUILD% redis

:: Run the producer first
echo 🕷️ Running scraper...
echo URL: %URL%
echo Keyword: %KEYWORD%
docker compose run --rm -e URL="%URL%" -e KEYWORD="%KEYWORD%" producer

:: Run LLM processor as its own container that will exit when done
echo 🧠 Starting LLM processor to process results...
docker compose run --rm llm python src/llm_main.py

:: Stop all services
echo Stopping services...
docker compose down

endlocal