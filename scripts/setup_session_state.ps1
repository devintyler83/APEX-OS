# DraftOS Session State Infrastructure Setup
# Run once from C:\DraftOS root to build entire state management system
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup_session_state.ps1

Write-Host ""
Write-Host "============================================================"
Write-Host "  DRAFTOS -- SESSION STATE INFRASTRUCTURE SETUP"
Write-Host "  " + (Get-Date -Format "dddd, MMMM dd, yyyy")
Write-Host "============================================================"
Write-Host ""

$root = Get-Location

# ------------------------------------------------------------
# STEP 1 -- Verify we are in DraftOS root
# ------------------------------------------------------------

if (-not (Test-Path "$root\scripts")) {
    Write-Host "[ERROR] No scripts folder found. Run this from C:\DraftOS root."
    exit 1
}

Write-Host "  Root confirmed: $root"
Write-Host ""

# ------------------------------------------------------------
# STEP 2 -- Create SESSION_STATE.md (Mode 2)
# ------------------------------------------------------------

$mode2State = @"
# SESSION STATE -- DRAFTOS MODE 2 (BUILD PLANNING)
Last Updated: $(Get-Date -Format "yyyy-MM-dd")
Session Baseline: 47

## MIGRATION LOG
Last Migration Completed: M0045 -- fill from your records
Next Migration: M0046 -- fill from your records

## MIGRATIONS PENDING
NONE

## SCHEMA STATE
Tables Modified This Session: NONE
Tables Added This Session: NONE
Pending Schema Decisions: NONE

## OPEN BUILD THREADS
NONE

## BLOCKERS
NONE

## NEXT SESSION OPENS WITH
NOT SET
"@

Set-Content -Path "$root\SESSION_STATE.md" -Value $mode2State -Encoding UTF8
Write-Host "  [CREATED] SESSION_STATE.md"

# ------------------------------------------------------------
# STEP 3 -- Create SESSION_STATE_MODE1.md
# ------------------------------------------------------------

$mode1State = @"
# SESSION STATE -- DRAFTOS MODE 1 (SPORTS ALMANAC)
Last Updated: $(Get-Date -Format "yyyy-MM-dd")
Session Baseline: 47

## ACTIVE EVALUATIONS
NONE

## COMPLETED THIS SESSION
NONE

## OPEN THREADS
NONE

## FRAMEWORK STATE
Archetype Library Version: v2.3
APEX Framework: No modifications
Active Divergence Flags: NONE

## COMP BUILD SEQUENCE
Last Position Completed: OG
Next Position: C

## NEXT SESSION OPENS WITH
NOT SET
"@

Set-Content -Path "$root\SESSION_STATE_MODE1.md" -Value $mode1State -Encoding UTF8
Write-Host "  [CREATED] SESSION_STATE_MODE1.md"

# ------------------------------------------------------------
# STEP 4 -- Create SESSION_STATE_MODE3.md
# ------------------------------------------------------------

$mode3State = @"
# SESSION STATE -- DRAFTOS MODE 3 (UI / VISUAL SYSTEMS)
Last Updated: $(Get-Date -Format "yyyy-MM-dd")
Session Baseline: 47

## COMPONENTS BUILT THIS SESSION
NONE

## ACTIVE DESIGN SYSTEM STATE
Color decisions: NONE
Typography decisions: NONE
Layout decisions: NONE

## OPEN THREADS
NONE

## FILE MANIFEST
NONE

## NEXT SESSION OPENS WITH
NOT SET
"@

Set-Content -Path "$root\SESSION_STATE_MODE3.md" -Value $mode3State -Encoding UTF8
Write-Host "  [CREATED] SESSION_STATE_MODE3.md"

# ------------------------------------------------------------
# STEP 5 -- Verify all six scripts exist
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================================"
Write-Host "  VERIFYING SCRIPTS"
Write-Host "============================================================"
Write-Host ""

$scripts = @(
    "scripts\open_session.py",
    "scripts\open_session_mode1.py",
    "scripts\open_session_mode3.py",
    "scripts\update_session_state.py",
    "scripts\update_session_state_mode1.py",
    "scripts\update_session_state_mode3.py"
)

$allGood = $true

foreach ($script in $scripts) {
    if (Test-Path "$root\$script") {
        Write-Host "  [OK]      $script"
    } else {
        Write-Host "  [MISSING] $script -- create this file before running sessions"
        $allGood = $false
    }
}

# ------------------------------------------------------------
# STEP 6 -- Verify PowerShell profile aliases
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================================"
Write-Host "  VERIFYING POWERSHELL ALIASES"
Write-Host "============================================================"
Write-Host ""

$profileContent = ""
if (Test-Path $PROFILE) {
    $profileContent = Get-Content $PROFILE -Raw
}

$aliases = @("draftos", "draftos1", "draftos3")

foreach ($alias in $aliases) {
    if ($profileContent -match "function $alias") {
        Write-Host "  [OK]      $alias"
    } else {
        Write-Host "  [MISSING] $alias -- add to PowerShell profile"
        $allGood = $false
    }
}

# ------------------------------------------------------------
# STEP 7 -- Final status
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================================"

if ($allGood) {
    Write-Host "  SETUP COMPLETE -- all state files and scripts verified"
    Write-Host "  Run draftos, draftos1, or draftos3 to open any session"
} else {
    Write-Host "  SETUP COMPLETE WITH WARNINGS -- resolve missing items above"
}

Write-Host "============================================================"
Write-Host ""