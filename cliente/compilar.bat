@echo off
echo Instalando lo necesario...
python -m pip install --upgrade pillow pyinstaller
echo Creando AutoClickerAL.exe...
python -m PyInstaller --onefile --noconsole --name "AutoClickerAL" AutoClickerAL.py
echo.
echo Listo: dist\AutoClickerAL.exe
pause
