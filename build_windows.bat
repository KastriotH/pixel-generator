@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo Random Pixel Image, GIF and H.264 Video Generator
echo ==============================================

where py >nul 2>nul
if errorlevel 1 (
    echo Python 3 launcher "py" was not found.
    echo Install Python from https://www.python.org/downloads/windows/
    echo Enable "Add Python to PATH" during installation.
    pause
    exit /b 1
)

py -3 -m pip install --upgrade pip
if errorlevel 1 goto error

py -3 -m pip install --upgrade numpy pillow imageio-ffmpeg pyinstaller
if errorlevel 1 goto error

py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name RandomPixelGenerator --collect-all imageio_ffmpeg --collect-all numpy random_pixel_generator.py
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
