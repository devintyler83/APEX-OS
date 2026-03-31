# DraftOS Session State Reset
# Wipes and reinitializes all three SESSION_STATE files to clean defaults
# Scripts and aliases are never touched
# Usage: powershell -ExecutionPolicy Bypass -File scripts/reset_session_state.ps1

param(
    [string]$Baseline = "",
    [string]$ArchetypeVersion = "v2.3",
    [string]$LastPosition = "NONE",
    [string]$NextPosition = "NONE",
    [string]$LastMigration = "NONE",
    [string]$NextMigration = "NONE"
)

Write-Host ""
Write-Host "============================================================"
Write-Host "  DRAFTOS -- SESSION STATE RESET"
Write-Host "  " + (Get-Date -Format "dddd, MMMM dd, yyyy")
Write-Host "============================================================"
Write-Host ""

$root = Get-Location

# ------------------------------------------------------------
# STEP 1 -- Verify root
# ------------------------------------------------------------

if (-not (Test-Path "$root\scripts")) {
    Write-Host "[ERROR] No scripts folder found. Run this from C:\DraftOS root."
    exit 1
}

# ------------------------------------------------------------
# STEP 2 -- Collect baseline if not passed as parameter
# ------------------------------------------------------------

if ($Baseline -eq "") {
    $Baseline = Read-Host "  Enter current session baseline number"
}

if ($LastMigration -eq "NONE") {
    $LastMigration = Read-Host "  Last migration completed (e.g. M0046 -- description)"
}

if ($NextMigration -eq "NONE") {
    $NextMigration = Read-Host "  Next migration (e.g. M0047 -- description)"
}

if ($LastPosition -eq "NONE") {
    $LastPosition = Read-Host "  Last comp build position completed (e.g. C)"
}

if ($NextPosition -eq "NONE") {
    $NextPosition = Read-Host "  Next comp build position (e.g. OT)"
}

Write-Host ""

# ------------------------------------------------------------
# STEP 3 -- Confirm before wiping
# ------------------------------------------------------------

Write-Host "  RESET PARAMETERS"
Write-Host "  Session Baseline:       $Baseline"
Write-Host "  Last Migration:         $LastMigration"
Write-Host "  Next Migration:         $NextMigration"
Write-Host "  Last Position:          $LastPosition"
Write-Host "  Next Position:          $NextPosition"
Write-Host "  Archetype Version:      $ArchetypeVersion"
Write-Host ""

$confirm = Read-Host "  Wipe and reinitialize all three state files? (yes to confirm)"

if ($confirm -ne "yes") {
    Write-Host ""
    Write-Host "  Reset cancelled. No files were modified."
    Write-Host ""
    exit 0
}

Write-Host ""

# ------------------------------------------------------------
# STEP 4 -- Reset SESSION_STATE.md (Mode 2)
# ------------------------------------------------------------

$mode2State = @"
# SESSION STATE -- DRAFTOS MODE 2 (BUILD PLANNING)
Last Updated: $(Get-Date -Format "yyyy-MM-dd")
Session Baseline: $Baseline

## MIGRATION LOG
Last Migration Completed: $LastMigration
Next Migration: $NextMigration

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
Write-Host "  [RESET]   SESSION_STATE.md"

# ------------------------------------------------------------
# STEP 5 -- Reset SESSION_STATE_MODE1.md
# ------------------------------------------------------------

$mode1State = @"
# SESSION STATE -- DRAFTOS MODE 1 (SPORTS ALMANAC)
Last Updated: $(Get-Date -Format "yyyy-MM-dd")
Session Baseline: $Baseline

## ACTIVE EVALUATIONS
NONE

## COMPLETED THIS SESSION
NONE

## OPEN THREADS
NONE

## FRAMEWORK STATE
Archetype Library Version: $ArchetypeVersion
APEX Framework: No modifications
Active Divergence Flags: NONE

## COMP BUILD SEQUENCE
Last Position Completed: $LastPosition
Next Position: $NextPosition

## NEXT SESSION OPENS WITH
NOT SET
"@

Set-Content -Path "$root\SESSION_STATE_MODE1.md" -Value $mode1State -Encoding UTF8
Write-Host "  [RESET]   SESSION_STATE_MODE1.md"

# ------------------------------------------------------------
# STEP 6 -- Reset SESSION_STATE_MODE3.md
# ------------------------------------------------------------

$mode3State = @"
# SESSION STATE -- DRAFTOS MODE 3 (UI / VISUAL SYSTEMS)
Last Updated: $(Get-Date -Format "yyyy-MM-dd")
Session Baseline: $Baseline

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
Write-Host "  [RESET]   SESSION_STATE_MODE3.md"

# ------------------------------------------------------------
# STEP 7 -- Final status
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================================"
Write-Host "  RESET COMPLETE"
Write-Host "  All three state files reinitialized to clean defaults"
Write-Host "  Scripts and aliases untouched"
Write-Host "  Run draftos, draftos1, or draftos3 to verify"
Write-Host "============================================================"
Write-Host ""