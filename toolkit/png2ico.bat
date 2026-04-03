@echo off
chcp 65001 >nul
echo ========================================
echo PNG 转换为多尺寸 ICO 工具
echo ========================================
echo.

set INPUT=%1
set OUTPUT=%~n1.ico

if "%INPUT%"=="" (
    echo [错误] 请拖拽 PNG 文件到此脚本上，或在命令行输入：
    echo   png2ico.bat your_icon.png
    pause
    exit /b 1
)

echo [!] 正在转换：%INPUT% → %OUTPUT%

python - <<EOF
from PIL import Image
import sys, os

input_file = r"%INPUT%"
output_file = r"%OUTPUT%"

img = Image.open(input_file)
# 生成常见尺寸：16, 32, 48, 256
sizes = [(16,16), (32,32), (48,48), (256,256)]
img.save(output_file, format="ICO", sizes=sizes)
print("[✓] 转换完成：", output_file)
EOF

if %errorlevel% neq 0 (
    echo [错误] 转换失败！
    pause
    exit /b 1
)

echo [✓] ICO 文件已生成：%OUTPUT%
pause
