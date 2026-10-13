param([switch]$Cpu, [switch]$SkipModel)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.venv-rag/Scripts/python.exe')) {
        python -m venv .venv-rag
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ required.' }
    }
    $ragPython = Join-Path $projectRoot '.venv-rag/Scripts/python.exe'
    $torchIndex = if ($Cpu) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu128' }
    & $ragPython -m pip install 'torch==2.11.0' --index-url $torchIndex
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }
    & $ragPython -m pip install -r backend/requirements-rag.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'RAG dependencies installation failed.' }
    & $ragPython -c "import json,pathlib,torch,transformers,qdrant_client; pathlib.Path('.venv-rag/rag-runtime.json').write_text(json.dumps({'verified':True,'torch':torch.__version__,'transformers':transformers.__version__}),encoding='utf-8')"
    if ($LASTEXITCODE -ne 0) { throw 'RAG import verification failed.' }
    if (-not $SkipModel) {
        & $ragPython scripts/download-rag-model.py
        if ($LASTEXITCODE -ne 0) { throw 'Model verification failed.' }
        & $ragPython scripts/rag-cli.py probe
        if ($LASTEXITCODE -ne 0) { throw 'Model inference failed.' }
        & $ragPython scripts/rag-cli.py build
        if ($LASTEXITCODE -ne 0) { throw 'Index build failed.' }
    }
} finally {
    Pop-Location
}
