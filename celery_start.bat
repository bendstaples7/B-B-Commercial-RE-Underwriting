@echo off
REM Start the Celery worker for B and B Real Estate Analyzer.
REM
REM Three layers of protection against env/path issues:
REM   1. load_dotenv() in celery_worker.py loads backend/.env automatically
REM   2. This script explicitly sets DATABASE_URL from .env as a fallback
REM   3. celery_worker.py asserts required vars are set before starting
REM
REM --pool=solo is required on Windows to prevent a multiprocessing
REM initialization crash (ValueError: not enough values to unpack).
REM Must run from the backend/ directory so Python can find the 'app' module.

cd /d "%~dp0backend"

REM Load .env variables into the current shell session as a fallback
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /v "^#" .env`) do (
    if not "%%A"=="" if not "%%B"=="" set "%%A=%%B"
)

celery -A celery_worker.celery worker --loglevel=info --concurrency=1 --pool=solo
