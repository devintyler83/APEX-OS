"""
APEX v2.3 DB write layer.
Idempotent — all writes use INSERT OR REPLACE via UNIQUE(prospect_id, season_id, model_version).
Backs up the DB before first write per run.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone

from draftos.config import PATHS


def backup_once(already_backed_up: bool) -> bool:
    """
    Create a timestamped DB backup if not already done this run.
    Returns True after backup completes (or if already done).
    Pass the return value forward as 'already_backed_up' in subsequent calls.
    """
    if already_backed_up:
        return True

    if not PATHS.db.exists():
        return True  # Nothing to back up

    backup_dir = PATHS.exports / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts          = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"draftos.sqlite.backup.apex_{ts}"
    shutil.copy2(PATHS.db, backup_path)
    print(f"  [backup] DB backed up -> {backup_path.name}")
    return True


def upsert_apex_score(
    conn,
    *,
    prospect_id:    int,
    season_id:      int,
    model_version:  str,
    apex_data:      dict,
    apex_composite: float,
    apex_tier:      str,
    pvc:            float,
    ras_score:      float | None = None,
) -> None:
    """
    INSERT OR REPLACE into apex_scores.
    Idempotent via UNIQUE(prospect_id, season_id, model_version).

    apex_data: parsed JSON dict returned by Claude.
    Computed fields (apex_composite, apex_tier, pvc) are supplied by the engine layer.
    """
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO apex_scores (
            prospect_id, season_id, model_version, scored_at,
            v_processing, v_athleticism, v_scheme_vers, v_comp_tough,
            v_character,  v_dev_traj, v_production, v_injury,
            c1_public_record, c2_motivation, c3_psych_profile,
            matched_archetype, archetype_gap, gap_label,
            raw_score, pvc, apex_composite, apex_tier,
            capital_base, capital_adjusted, eval_confidence,
            tags, strengths, red_flags,
            schwesinger_full, schwesinger_half, smith_rule,
            ras_score,
            failure_mode_primary, failure_mode_secondary,
            signature_play, translation_risk
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?,
            ?, ?,
            ?, ?
        )
        ON CONFLICT(prospect_id, season_id, model_version) DO UPDATE SET
            scored_at              = excluded.scored_at,
            v_processing           = excluded.v_processing,
            v_athleticism          = excluded.v_athleticism,
            v_scheme_vers          = excluded.v_scheme_vers,
            v_comp_tough           = excluded.v_comp_tough,
            v_character            = excluded.v_character,
            v_dev_traj             = excluded.v_dev_traj,
            v_production           = excluded.v_production,
            v_injury               = excluded.v_injury,
            c1_public_record       = excluded.c1_public_record,
            c2_motivation          = excluded.c2_motivation,
            c3_psych_profile       = excluded.c3_psych_profile,
            matched_archetype      = excluded.matched_archetype,
            archetype_gap          = excluded.archetype_gap,
            gap_label              = excluded.gap_label,
            raw_score              = excluded.raw_score,
            pvc                    = excluded.pvc,
            apex_composite         = excluded.apex_composite,
            apex_tier              = excluded.apex_tier,
            capital_base           = excluded.capital_base,
            capital_adjusted       = excluded.capital_adjusted,
            eval_confidence        = excluded.eval_confidence,
            tags                   = excluded.tags,
            strengths              = excluded.strengths,
            red_flags              = excluded.red_flags,
            schwesinger_full       = excluded.schwesinger_full,
            schwesinger_half       = excluded.schwesinger_half,
            smith_rule             = excluded.smith_rule,
            ras_score              = excluded.ras_score,
            failure_mode_primary   = excluded.failure_mode_primary,
            failure_mode_secondary = excluded.failure_mode_secondary,
            signature_play         = excluded.signature_play,
            translation_risk       = excluded.translation_risk
        """,
        (
            prospect_id, season_id, model_version, now,
            apex_data.get("v_processing"),
            apex_data.get("v_athleticism"),
            apex_data.get("v_scheme_vers"),
            apex_data.get("v_comp_tough"),
            apex_data.get("v_character"),
            apex_data.get("v_dev_traj"),
            apex_data.get("v_production"),
            apex_data.get("v_injury"),
            apex_data.get("c1_public_record"),
            apex_data.get("c2_motivation"),
            apex_data.get("c3_psych_profile"),
            apex_data.get("archetype"),
            apex_data.get("archetype_gap"),
            apex_data.get("gap_label"),
            apex_data.get("raw_score"),
            pvc,
            apex_composite,
            apex_tier,
            apex_data.get("capital_base"),
            apex_data.get("capital_adjusted"),
            apex_data.get("eval_confidence"),
            apex_data.get("tags", ""),
            apex_data.get("strengths", ""),
            apex_data.get("red_flags", ""),
            int(apex_data.get("schwesinger_full", 0)),
            int(apex_data.get("schwesinger_half", 0)),
            int(apex_data.get("smith_rule", 0)),
            ras_score,
            apex_data.get("failure_mode_primary"),
            apex_data.get("failure_mode_secondary"),
            apex_data.get("signature_play"),
            apex_data.get("translation_risk"),
        ),
    )
    conn.commit()


def upsert_divergence_flag(
    conn,
    *,
    prospect_id:    int,
    season_id:      int,
    model_version:  str,
    apex_composite: float,
    apex_tier:      str,
    apex_capital:   str | None,
    consensus_rank: int,
    consensus_tier: str | None,
    divergence:     dict,
    position_tier:  str | None = None,
) -> None:
    """
    INSERT OR REPLACE into divergence_flags.
    Idempotent via UNIQUE(prospect_id, season_id, model_version).

    divergence: dict returned by engine.compute_divergence()
    position_tier: 'premium' or 'non_premium' (optional; populated by batch recompute)
      divergence_rank_delta is NULL here — only the batch divergence recompute can
      populate it because rank-relative ordering requires all scored prospects.
      divergence_raw_delta is written from divergence['divergence_score'] (old method).
    """
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO divergence_flags (
            prospect_id, season_id, computed_at, model_version,
            apex_composite, apex_tier, apex_capital,
            consensus_ovr_rank, consensus_tier,
            divergence_score, rounds_diff,
            divergence_flag, divergence_mag, apex_favors,
            divergence_raw_delta, position_tier
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?
        )
        ON CONFLICT(prospect_id, season_id, model_version) DO UPDATE SET
            computed_at          = excluded.computed_at,
            apex_composite       = excluded.apex_composite,
            apex_tier            = excluded.apex_tier,
            apex_capital         = excluded.apex_capital,
            consensus_ovr_rank   = excluded.consensus_ovr_rank,
            consensus_tier       = excluded.consensus_tier,
            divergence_score     = excluded.divergence_score,
            rounds_diff          = excluded.rounds_diff,
            divergence_flag      = excluded.divergence_flag,
            divergence_mag       = excluded.divergence_mag,
            apex_favors          = excluded.apex_favors,
            divergence_raw_delta = excluded.divergence_raw_delta,
            position_tier        = excluded.position_tier
        """,
        (
            prospect_id, season_id, now, model_version,
            apex_composite, apex_tier, apex_capital,
            float(consensus_rank), consensus_tier,
            divergence["divergence_score"],
            divergence["rounds_diff"],
            divergence["divergence_flag"],
            divergence["divergence_mag"],
            divergence["apex_favors"],
            # divergence_raw_delta: old raw score delta (diagnostic)
            divergence.get("divergence_score"),
            position_tier,
        ),
    )
    conn.commit()
