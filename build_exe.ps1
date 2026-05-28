$ErrorActionPreference = "Stop"

$python = if (Test-Path ".\.venv\Scripts\python.exe") {
  Resolve-Path ".\.venv\Scripts\python.exe"
} else {
  "python"
}

$tmp = Join-Path (Resolve-Path ".").Path "pip_tmp"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:TEMP = $tmp
$env:TMP = $tmp

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt
& $python -m pip install pyinstaller

$hooksDir = & $python -c "import pathlib, playwright._impl.__pyinstaller as p; print(pathlib.Path(p.__file__).resolve().parent)"

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --runtime-tmpdir .runtime `
  --additional-hooks-dir "$hooksDir" `
  --name EasyQuestionPicker `
  app.py
