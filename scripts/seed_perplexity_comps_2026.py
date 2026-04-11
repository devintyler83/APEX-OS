"""
Seed Perplexity-derived historical comp records into historical_comps table.

Source: data/imports/comps/perplexity_historical_comps_2026.csv
Coverage: all 13 APEX position groups, 66 archetypes, ~198 rows.

Column mapping (CSV → DB):
  playername        → player_name
  archetypecode     → archetype_code  (DT-* remapped to IDL-*)
  outcome           → translation_outcome  (HIT / PARTIAL / MISS)
  compconfidence    → comp_confidence      (A / B / C)
  era               → era_bracket
  mechanism_summary → mechanism + outcome_summary (CSV has one text field; fills both)
  fmcode            → fm_code
  [derived]         → position  (extracted from archetype prefix; DT prefix → IDL)

Idempotent: INSERT OR IGNORE on UNIQUE(player_name, archetype_code).
Safe to re-run — existing rows (including FM reference rows) are never modified.

Usage:
    python -m scripts.seed_perplexity_comps_2026 --apply 0   # dry run
    python -m scripts.seed_perplexity_comps_2026 --apply 1   # write
"""
from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path

from draftos.config import PATHS
from draftos.db.connect import connect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CSV_PATH = PATHS.root / "data" / "imports" / "comps" / "perplexity_historical_comps_2026.csv"

REQUIRED_COLUMNS = {
    "playername",
    "archetypecode",
    "outcome",
    "compconfidence",
    "era",
    "mechanism_summary",
    "fmcode",
}

# The CSV uses "DT" prefix; APEX uses "IDL" throughout.
# Remap the archetype prefix before storing.
_ARCHETYPE_PREFIX_REMAP: dict[str, str] = {
    "DT": "IDL",
}

# Map archetype prefix → DB position value.
# Perplexity comps are position comps, not season comps — position is static.
_PREFIX_TO_POSITION: dict[str, str] = {
    "QB":   "QB",
    "CB":   "CB",
    "EDGE": "EDGE",
    "IDL":  "IDL",
    "ILB":  "ILB",
    "OLB":  "OLB",
    "OT":   "OT",
    "OG":   "OG",
    "C":    "C",
    "TE":   "TE",
    "RB":   "RB",
    "S":    "S",
    "WR":   "WR",
}

VALID_OUTCOMES = {"HIT", "PARTIAL", "MISS"}
VALID_CONFIDENCES = {"A", "B", "C"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _remap_archetype(raw_code: str) -> str:
    """
    Remap archetype prefix if needed (e.g. 'DT-3' → 'IDL-3').
    Returns the canonical APEX archetype code.
    """
    raw_code = raw_code.strip()
    if "-" not in raw_code:
        return raw_code
    prefix, suffix = raw_code.split("-", 1)
    prefix = _ARCHETYPE_PREFIX_REMAP.get(prefix.upper(), prefix.upper())
    return f"{prefix}-{suffix}"


def _position_from_archetype(archetype_code: str) -> str | None:
    """
    Derive the DB `position` value from the canonical archetype code.
    'IDL-3' → 'IDL', 'QB-1' → 'QB', etc.
    Returns None if the prefix is unrecognised.
    """
    if "-" not in archetype_code:
        return None
    prefix = archetype_code.split("-", 1)[0].upper()
    return _PREFIX_TO_POSITION.get(prefix)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"FAIL  CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SystemExit(f"FAIL  CSV has no header row: {path}")
        actual = {h.strip().lower() for h in reader.fieldnames}
        missing = REQUIRED_COLUMNS - actual
        if missing:
            raise SystemExit(
                f"FAIL  CSV missing required columns: {sorted(missing)}\n"
                f"      Found: {sorted(actual)}"
            )
        return [dict(row) for row in reader]


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------

def _normalize(raw: dict[str, str]) -> dict[str, str]:
    """Strip whitespace and normalise casing on controlled fields."""
    return {
        "playername":        (raw.get("playername") or "").strip(),
        "archetypecode":     (raw.get("archetypecode") or "").strip(),
        "outcome":           (raw.get("outcome") or "").strip().upper(),
        "compconfidence":    (raw.get("compconfidence") or "").strip().upper(),
        "era":               (raw.get("era") or "").strip(),
        "mechanism_summary": (raw.get("mechanism_summary") or "").strip(),
        "fmcode":            (raw.get("fmcode") or "").strip().upper() or None,
    }


def _validate(norm: dict[str, str]) -> tuple[bool, str]:
    """Return (ok, reason). reason is '' when ok."""
    if not norm["playername"]:
        return False, "empty playername"
    if not norm["archetypecode"]:
        return False, "empty archetypecode"
    if norm["outcome"] not in VALID_OUTCOMES:
        return False, f"invalid outcome '{norm['outcome']}'"
    if norm["compconfidence"] not in VALID_CONFIDENCES:
        return False, f"invalid compconfidence '{norm['compconfidence']}'"
    if not norm["mechanism_summary"]:
        return False, "empty mechanism_summary"
    fc = norm["fmcode"]
    if fc and not fc.startswith("FM-"):
        return False, f"unrecognised fm_code '{fc}'"
    return True, ""


def _build_db_row(norm: dict[str, str]) -> dict | None:
    """
    Map normalised CSV fields to historical_comps DB columns.
    Returns None if archetype prefix is unrecognised (skipped with warning).
    """
    arch_code = _remap_archetype(norm["archetypecode"])
    position  = _position_from_archetype(arch_code)
    if position is None:
        return None  # unrecognised prefix — skip

    era = norm["era"] or "Unknown"
    mech = norm["mechanism_summary"]

    return {
        "player_name":        norm["playername"],
        "position":           position,
        "archetype_code":     arch_code,
        "mechanism":          mech,
        "translation_outcome": norm["outcome"],
        "fm_code":            norm["fmcode"],
        "fm_mechanism":       None,
        "outcome_summary":    mech,       # single text field covers both in CSV
        "era_bracket":        era,
        "peak_years":         None,
        "comp_confidence":    norm["compconfidence"],
        "scheme_context":     None,
        "signature_trait":    None,
        "pre_draft_signal":   None,
        "is_fm_reference":    0,          # Perplexity comps are position comps only
    }


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def _seed(conn, db_rows: list[dict]) -> dict[str, int]:
    """
    INSERT OR IGNORE each row.
    Returns counts: inserted, skipped_duplicate, scanned.
    """
    inserted = 0
    skipped_dup = 0

    for row in db_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO historical_comps (
                player_name, position, archetype_code,
                mechanism, translation_outcome, fm_code,
                fm_mechanism, outcome_summary, era_bracket,
                peak_years, comp_confidence, scheme_context,
                signature_trait, pre_draft_signal, is_fm_reference,
                created_at, updated_at
            )
            VALUES (
                :player_name, :position, :archetype_code,
                :mechanism, :translation_outcome, :fm_code,
                :fm_mechanism, :outcome_summary, :era_bracket,
                :peak_years, :comp_confidence, :scheme_context,
                :signature_trait, :pre_draft_signal, :is_fm_reference,
                datetime('now'), datetime('now')
            )
            """,
            row,
        )
        if conn.execute("SELECT changes()").fetchone()[0] == 1:
            inserted += 1
        else:
            skipped_dup += 1

    return {"inserted": inserted, "skipped_duplicate": skipped_dup}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Seed Perplexity historical comps into historical_comps table."
    )
    ap.add_argument(
        "--apply", type=int, default=0, choices=[0, 1],
        help="0 = dry run (default), 1 = write to DB",
    )
    args = ap.parse_args()
    apply = bool(args.apply)

    if not PATHS.db.exists():
        raise SystemExit(f"FAIL  DB not found: {PATHS.db}")

    raw_rows = _read_csv(CSV_PATH)
    print(f"{'APPLY' if apply else 'DRY RUN'}  seed_perplexity_comps_2026")
    print(f"  CSV : {CSV_PATH.name}  ({len(raw_rows)} rows scanned)")

    # --- Validate + build DB rows ---
    db_rows: list[dict] = []
    invalid: list[tuple[int, str]] = []
    unrecognised_arch: list[str] = []

    for i, raw in enumerate(raw_rows, start=2):   # row 1 = header
        norm = _normalize(raw)
        ok, reason = _validate(norm)
        if not ok:
            invalid.append((i, reason))
            continue
        db_row = _build_db_row(norm)
        if db_row is None:
            prefix = norm["archetypecode"].split("-")[0]
            unrecognised_arch.append(f"row {i}: {norm['archetypecode']} (prefix={prefix})")
            continue
        db_rows.append(db_row)

    print(f"  Valid rows ready : {len(db_rows)}")
    if invalid:
        print(f"  Invalid (skipped): {len(invalid)}")
        for row_num, reason in invalid[:10]:
            print(f"    row {row_num}: {reason}")
        if len(invalid) > 10:
            print(f"    ... and {len(invalid) - 10} more")
    if unrecognised_arch:
        print(f"  Unknown arch prefix (skipped): {len(unrecognised_arch)}")
        for msg in unrecognised_arch[:5]:
            print(f"    {msg}")

    if not apply:
        # Dry-run: count what would be inserted vs skipped-duplicate
        with connect() as conn:
            would_insert = 0
            would_skip_dup = 0
            for row in db_rows:
                exists = conn.execute(
                    "SELECT 1 FROM historical_comps WHERE player_name=? AND archetype_code=?",
                    (row["player_name"], row["archetype_code"]),
                ).fetchone()
                if exists:
                    would_skip_dup += 1
                else:
                    would_insert += 1
        print(f"\n  Would insert      : {would_insert}")
        print(f"  Would skip (dup)  : {would_skip_dup}  (UNIQUE constraint)")
        print("\nDRY RUN complete — no changes made.")
        print("Rerun with --apply 1 to write.")
        return

    # --- Backup ---
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = PATHS.db.with_suffix(f".bak_s_perpcomps_{ts}.sqlite")
    shutil.copy2(PATHS.db, backup)
    print(f"\n  Backup: {backup.name}")

    # --- Write ---
    with connect() as conn:
        counts = _seed(conn, db_rows)
        conn.commit()

    print(f"\n  Inserted          : {counts['inserted']}")
    print(f"  Skipped (dup)     : {counts['skipped_duplicate']}")
    print("\nSEED APPLIED")

    # Verification hint
    print("\nVerify:")
    print("  sqlite3 data/edge/draftos.sqlite "
          "\"SELECT COUNT(*) FROM historical_comps WHERE is_fm_reference=0;\"")


if __name__ == "__main__":
    main()
