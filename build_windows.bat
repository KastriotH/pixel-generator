@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo Pixel Generator - Numba + OpenCL GPU Fractal Edition
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

py -3 -m pip install --upgrade numpy "numba>=0.61.0" "llvmlite>=0.44.0" "pyopencl>=2025.2.6" pillow imageio-ffmpeg ttkbootstrap==2.2.7 pyinstaller pyinstaller-hooks-contrib
if errorlevel 1 goto error

py -3 -c "import numba, llvmlite, pyopencl; print('Numba', numba.__version__, '| llvmlite', llvmlite.__version__, '| PyOpenCL', pyopencl.VERSION_TEXT)"
if errorlevel 1 goto error

rem NumPy, Numba and llvmlite use PyInstaller's maintained hooks. PyOpenCL is collected narrowly: extension module, native DLLs, package data and metadata (avoid collecting its tests).
rem The NVIDIA OpenCL driver/runtime is provided by the installed GeForce driver and is not bundled into this EXE.
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name RandomPixelGenerator --collect-all imageio_ffmpeg --collect-all ttkbootstrap --collect-binaries pyopencl --collect-data pyopencl --hidden-import pyopencl._cl --copy-metadata pyopencl random_pixel_generator.py
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
