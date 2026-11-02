# Builds dist\CoCMacro.exe (single file, no console). Run from the repo root:
#   python -m pip install -r requirements.txt -r requirements-build.txt
#   powershell -File scripts\build_exe.ps1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name CoCMacro `
  --add-data "cocmacro\glyphs.npz;cocmacro" `
  --add-data "cocmacro\defaults\templates;cocmacro\defaults\templates" `
  --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 `
  cocmacro\__main__.py
