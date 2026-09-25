@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在生成并启动本地预览……
python build.py --serve --open
if errorlevel 1 (
  echo.
  echo 启动失败：请确认已安装 Python，并在本目录运行过  pip install -r requirements.txt
)
pause
