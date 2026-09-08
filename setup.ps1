# =============================================================================
# RTP Deal Intelligence — fresh machine bootstrap
#
# Installs Python 3.12, creates the venv, installs dependencies, and checks
# that .env is present. Safe to re-run: every step is idempotent.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# =============================================================================

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Say($msg)  { Write-Host "  $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  WARN $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "RTP Deal Intelligence - environment setup" -ForegroundColor White
Write-Host "=========================================" -ForegroundColor White
Write-Host ""

# -----------------------------------------------------------------------------
# 1. Python 3.12
#
# CLAUDE.md pins 3.12. Do not silently accept a newer interpreter -- the pinned
# pandas/numpy builds in requirements.txt may not have wheels for it, and you
# would spend an hour on compiler errors instead of on the actual problem.
# -----------------------------------------------------------------------------
Say "Checking for Python 3.12..."

$py = $null
try {
    $probe = & py -3.12 --version 2>&1
    if ($LASTEXITCODE -eq 0) { $py = 'py -3.12'; Ok "found: $probe" }
} catch { }

if (-not $py) {
    Warn "Python 3.12 not found. Installing via winget..."
    winget install --id Python.Python.3.12 --source winget `
        --accept-package-agreements --accept-source-agreements
    Warn "Installed. CLOSE THIS TERMINAL, open a new one, and re-run setup.ps1"
    Warn "(the PATH change only applies to new shells)"
    exit 0
}

# -----------------------------------------------------------------------------
# 2. Virtual environment
# -----------------------------------------------------------------------------
if (Test-Path ".venv") {
    Ok ".venv already exists"
} else {
    Say "Creating .venv..."
    Invoke-Expression "$py -m venv .venv"
    Ok ".venv created"
}

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "venv python missing at $venvPy" }

# -----------------------------------------------------------------------------
# 3. Dependencies
# -----------------------------------------------------------------------------
Say "Upgrading pip..."
& $venvPy -m pip install --quiet --upgrade pip

Say "Installing requirements.txt (this takes a few minutes)..."
& $venvPy -m pip install --quiet -r requirements.txt
Ok "dependencies installed"

# -----------------------------------------------------------------------------
# 4. .env
#
# Gitignored by design, so a fresh clone never has it. Railway is the only
# place these values still exist.
# -----------------------------------------------------------------------------
Write-Host ""
if (Test-Path ".env") {
    Ok ".env present"

    $required = @('DATABASE_URL','ANTHROPIC_API_KEY','GMAIL_CLIENT_ID',
                  'GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN')
    $content = Get-Content ".env" -Raw
    $missing = @()
    foreach ($k in $required) {
        if ($content -notmatch "(?m)^\s*$k\s*=\s*\S") { $missing += $k }
    }
    if ($missing.Count -gt 0) {
        Warn "these keys are missing or blank in .env:"
        $missing | ForEach-Object { Warn "    $_" }
    } else {
        Ok "all required keys present"
    }
} else {
    Warn ".env NOT FOUND -- nothing can connect without it."
    Warn ""
    Warn "  Reconstruct it from Railway:"
    Warn "    railway variables --json > railway_vars.json"
    Warn "    .venv\Scripts\python.exe scripts\env_from_railway.py railway_vars.json"
}

Write-Host ""
Write-Host "Next:  .venv\Scripts\python.exe scripts\health_check.py" -ForegroundColor White
Write-Host ""
