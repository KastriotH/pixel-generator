@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo Random Pixel Image, GIF and H.264 Video Generator
echo ==============================================

where py >nul 2>nul
if errorlevel 1 (
    echo Python 3 launcher "py" was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
    echo Enable "Add Python to PATH" during installation.
    pause
    exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Pixel Generator themes require Python 3.10 or newer.
    pause
    exit /b 1
)

py -3 -m pip install --upgrade pip
if errorlevel 1 goto error

py -3 -m pip install --upgrade numpy pillow imageio-ffmpeg ttkbootstrap==2.2.7 pyinstaller
if errorlevel 1 goto error

rem NumPy is collected by PyInstaller's built-in hook. Avoid --collect-all numpy: it scans NumPy test packages and can warn about optional pytest.
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name RandomPixelGenerator --collect-all imageio_ffmpeg --collect-all ttkbootstrap random_pixel_generator.py
if errorlevel 1 goto error

echo.
echo BUILD COMPLETED!
echo Standalone EXE:
echo %CD%\dist\RandomPixelGenerator.exe
pause
exit /b 0

:error
echo.
echo BUILD FAILED. Review the messages above.
pause
exit /b 1
