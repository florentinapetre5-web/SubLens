@echo off
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    python -m venv venv
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install Pillow pytesseract PySide6 mss keyboard pywin32
) else (
    call venv\Scripts\activate.bat
    python -c "import PySide6" 2>NUL || pip install PySide6
    python -c "import mss" 2>NUL || pip install mss
    python -c "import keyboard" 2>NUL || pip install keyboard
    python -c "import win32gui" 2>NUL || pip install pywin32
)
python sublens.py
pause
