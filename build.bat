@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
echo ========================================
echo ESP32 S3 自动烧录工具 - PyQt 打包脚本
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python！
    echo 建议：使用虚拟环境后再运行此脚本
    pause
    exit /b 1
)

echo [OK] Python 已安装
echo.

REM Check PyInstaller
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] PyInstaller 未安装，正在自动安装...
    REM pip 安装 PyInstaller 时版本约束须加引号（见下一行）
    pip install -q "pyinstaller>=6.0.0"
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败！
        pause
        exit /b 1
    )
    echo [OK] PyInstaller 安装成功
    echo.
) else (
    echo [OK] PyInstaller 已安装
    echo.
)

REM Check deps (install requirements if missing)
echo 正在检查项目依赖...
python -c "import serial; import esptool" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] 检测到缺少依赖，正在安装...
    pip install -q -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败！
        pause
        exit /b 1
    )
)
echo [OK] 依赖已就绪
echo.

REM Clean old build
if exist build (
    echo [*] 清理旧的 build 目录...
    rmdir /s /q build
)
if exist dist (
    echo [*] 清理旧的 dist 目录...
    rmdir /s /q dist
)
echo.

REM PyQt onefile build (config.json is created beside exe at runtime, not bundled)
echo ========================================
echo 正在打包固件烧录工具（PyQt）...
echo ========================================

set ICON_PATH=app_exe.ico
set ENTRY=main.py
set NAME=esp32_flasher

if not exist "%ICON_PATH%" (
    echo [错误] 找不到图标文件：%ICON_PATH%
    echo 请把 app_exe.ico 放到本目录：%CD%
    pause
    exit /b 1
)

pyinstaller --onefile --windowed --name %NAME% ^
    --icon "%ICON_PATH%" ^
    --add-data "%ICON_PATH%;." ^
    --hidden-import=esptool ^
    --hidden-import=esptool.cmds ^
    --hidden-import=esptool.targets ^
    --hidden-import=esptool.targets.esp32 ^
    --hidden-import=esptool.targets.esp8266 ^
    --hidden-import=esptool.targets.esp32s2 ^
    --hidden-import=esptool.targets.esp32s3 ^
    --hidden-import=esptool.targets.esp32c2 ^
    --hidden-import=esptool.targets.esp32c3 ^
    --hidden-import=esptool.targets.esp32c6 ^
    --hidden-import=esptool.targets.esp32c5 ^
    --hidden-import=esptool.targets.esp32c61 ^
    --hidden-import=esptool.targets.esp32e22 ^
    --hidden-import=esptool.targets.esp32h2 ^
    --hidden-import=esptool.targets.esp32h21 ^
    --hidden-import=esptool.targets.esp32h4 ^
    --hidden-import=esptool.targets.esp32p4 ^
    --hidden-import=esptool.loader ^
    --hidden-import=esptool.util ^
    --hidden-import=serial ^
    --hidden-import=serial.tools ^
    --hidden-import=serial.tools.list_ports ^
    --hidden-import=esptool.targets.esp32s31 ^
    --collect-all=esptool ^
    %ENTRY%

if %errorlevel% neq 0 (
    echo [错误] 固件烧录工具（PyQt）打包失败！
    pause
    exit /b 1
)

echo [OK] 固件烧录工具（PyQt）打包成功！
echo.

echo ========================================
echo 打包完成！
echo ========================================
echo.
echo 输出文件位置：
echo   - dist\%NAME%.exe
echo.

echo.
echo 按任意键退出...
pause >nul
