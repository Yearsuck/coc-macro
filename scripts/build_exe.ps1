# Builds dist\CoCMacro.exe (single file, no console). Run from the repo root:
#   python -m pip install -r requirements.txt -r requirements-build.txt
#   powershell -File scripts\build_exe.ps1
$py = if (Test-Path .venv\Scripts\python.exe) { '.venv\Scripts\python.exe' } else { 'python' }   # the project's own environment has OpenCV etc.
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name CoCMacro `
  --add-data "cocmacro\glyphs.npz;cocmacro" `
  --add-data "cocmacro\counter_zero.npz;cocmacro" `
  --add-data "cocmacro\defaults\templates;cocmacro\defaults\templates" `
  --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 `
  cocmacro\__main__.py
