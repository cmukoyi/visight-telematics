@echo off
REM Local test runner for Windows
REM Usage: run_tests.bat

setlocal enabledelayedexpansion

echo ================================
echo 🧪 Running Backend Tests
echo ================================
echo.

cd /d "%~dp0\gps-tracker\backend" || exit /b 1

REM Check if venv exists
if not exist "venv" (
    echo ⚠️  Virtual environment not found. Creating...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dev dependencies
echo 📦 Installing test dependencies...
pip install -q -r requirements.txt
pip install -q -r requirements-dev.txt

REM Run pytest with coverage
echo.
echo 🚀 Running pytest...
pytest ^
    tests/ ^
    --cov=app ^
    --cov-report=term-missing ^
    --cov-report=html ^
    -v

if errorlevel 1 (
    echo.
    echo ❌ Tests failed! Fix errors above before pushing.
    exit /b 1
)

echo.
echo ✅ All tests passed!
echo.
echo Next steps:
echo   1. Review test output above
echo   2. If all tests passed, push to git:
echo      git add .
echo      git commit -m "feat: add feature"
echo      git push origin main
echo.

endlocal
