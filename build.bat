@echo off
setlocal

:: Get URL and keyword from arguments, or use defaults
set "URL=%~1"
if "%URL%"=="" set "URL=https://example.com"

set "KEYWORD=%~2"
if "%KEYWORD%"=="" set "KEYWORD=python"

:: Check if rebuild is needed
set "REBUILD="
if "%3"=="--rebuild" set "REBUILD=--build"

:: Start services (only rebuild if explicitly requested)
echo 🚀 Starting services...
docker compose up -d --no-deps %REBUILD% redis llm

:: Run scraper and display results in parallel
echo 🕷️ Running scraper and processing...
echo URL: %URL%
echo Keyword: %KEYWORD%
start /B cmd /c "docker compose run --rm --workdir /app producer python src/main.py --url "%URL%" --keyword "%KEYWORD%""
start /B cmd /c "timeout /t 20 /nobreak && docker compose exec llm python src/main.py --read-only"

endlocal