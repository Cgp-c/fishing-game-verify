@echo off
chcp 936 >nul
cd /d "%~dp0game"
echo ============================================
echo   简单钓鱼游戏验证 - 启动中...
echo   关闭游戏窗口即可退出
echo ============================================
python main.py %*
if errorlevel 1 (
  echo.
  echo [出错] 请确认已安装 Python 和 Pillow: pip install pillow
  pause
)
