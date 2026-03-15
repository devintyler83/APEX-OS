"""
DraftOS Prospect One-Pager PDF Generator.

Produces a single-page PDF for any prospect in the universe.
Fully scored prospects get the complete card.
Consensus-only prospects get a clean partial card — no crashes, no ugly blanks.

Usage (CLI):
    python -m scripts.generate_prospect_pdf_2026 --prospect-id 9 --season 2026

Usage (Streamlit / programmatic):
    from scripts.generate_prospect_pdf_2026 import generate_pdf
    pdf_path = generate_pdf(prospect_id=9, season_id=1)

Output: C:\\DraftOS\\exports\\reports\\pdf\\{prospect_id}_{name_key}_{date}.pdf
Idempotent — overwrites prior PDF for same prospect.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from draftos.db.connect import connect
from draftos.config import PATHS

SEASON_ID = 1

# ── Color palette (matches DraftOS dark theme as close as reportlab allows) ──
C_BG         = colors.HexColor("#0f1117")
C_CARD       = colors.HexColor("#1a1d2e")
C_ACCENT     = colors.HexColor("#00d4aa")   # teal — APEX/RPG scores
C_GOLD       = colors.HexColor("#f5c518")   # DAY1/DAY2 tier
C_RED        = colors.HexColor("#e05c5c")   # red flags
C_GREEN      = colors.HexColor("#4caf82")   # strengths
C_MUTED      = colors.HexColor("#8892a4")   # secondary text
C_WHITE      = colors.HexColor("#e8eaf0")
C_FM_RED     = colors.HexColor("#c0392b")
C_FM_ORANGE  = colors.HexColor("#e67e22")

TIER_COLORS = {
    "ELITE":        colors.HexColor("#9b59b6"),
    "DAY1":         colors.HexColor("#f5c518"),
    "DAY2":         colors.HexColor("#3498db"),
    "DAY3":         colors.HexColor("#7f8c8d"),
    "UDFA":         colors.HexColor("#555555"),
}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", text.lower().strip())


def _fetch_prospect_data(conn, prospect_id: int, season_id: int) -> dict:
    """
    Pull all data needed for the PDF from DB.
    Returns a dict — missing fields are None, never KeyError.
    """
    # Core prospect row
    p = conn.execute(
        """
        SELECT p.prospect_id, p.display_name, p.full_name, p.position_group,
               p.school_canonical, p.name_key
        FROM prospects p
        WHERE p.prospect_id = ? AND p.season_id = ?
        """,
        (prospect_id, season_id),
    ).fetchone()

    if not p:
        raise ValueError(f"Prospect {prospect_id} not found in season {season_id}")

    data = dict(p)

    # Consensus
    cons = conn.execute(
        """
        SELECT consensus_rank, score AS consensus_score, tier AS consensus_tier
        FROM prospect_consensus_rankings
        WHERE prospect_id = ? AND season_id = ?
        """,
        (prospect_id, season_id),
    ).fetchone()
    data["consensus_rank"]  = cons["consensus_rank"]  if cons else None
    data["consensus_score"] = cons["consensus_score"] if cons else None
    data["consensus_tier"]  = cons["consensus_tier"]  if cons else None

    # RAS
    ras = conn.execute(
        "SELECT ras_total FROM ras WHERE prospect_id = ? AND ras_total IS NOT NULL LIMIT 1",
        (prospect_id,),
    ).fetchone()
    data["ras_total"] = ras["ras_total"] if ras else None

    # APEX scores — prefer v2.3, fall back to v2.2
    apex = conn.execute(
        """
        SELECT matched_archetype, archetype_gap, gap_label,
               raw_score, pvc, apex_composite, apex_tier,
               capital_base, capital_adjusted, eval_confidence,
               strengths, red_flags, tags,
               failure_mode_primary, signature_play, translation_risk,
               v_processing, v_athleticism, v_scheme_vers, v_comp_tough,
               v_character, v_dev_traj, v_production, v_injury,
               model_version, smith_rule, schwesinger_full
        FROM apex_scores
        WHERE prospect_id = ? AND season_id = ?
        ORDER BY CASE model_version
            WHEN 'apex_v2.3' THEN 1
            WHEN 'apex_v2.2' THEN 2
            ELSE 3
        END
        LIMIT 1
        """,
        (prospect_id, season_id),
    ).fetchone()

    if apex:
        for col in apex.keys():
            data[col] = apex[col]
    else:
        for col in [
            "matched_archetype", "archetype_gap", "gap_label",
            "raw_score", "pvc", "apex_composite", "apex_tier",
            "capital_base", "capital_adjusted", "eval_confidence",
            "strengths", "red_flags", "tags",
            "failure_mode_primary", "signature_play", "translation_risk",
            "v_processing", "v_athleticism", "v_scheme_vers", "v_comp_tough",
            "v_character", "v_dev_traj", "v_production", "v_injury",
            "model_version", "smith_rule", "schwesinger_full",
        ]:
            data[col] = None

    # Divergence
    div = conn.execute(
        """
        SELECT divergence_flag, divergence_rank_delta
        FROM divergence_flags
        WHERE prospect_id = ? AND season_id = ?
        ORDER BY div_id DESC LIMIT 1
        """,
        (prospect_id, season_id),
    ).fetchone()
    data["divergence_flag"]        = div["divergence_flag"]        if div else None
    data["divergence_rank_delta"]  = div["divergence_rank_delta"]  if div else None

    return data


def _trait_bar_table(data: dict) -> Optional[Table]:
    """
    Build a compact trait vector mini-table.
    Returns None if no trait data available.
    """
    TRAITS = [
        ("Processing",   "v_processing"),
        ("Athleticism",  "v_athleticism"),
        ("Scheme Vers.", "v_scheme_vers"),
        ("Comp. Tough",  "v_comp_tough"),
        ("Character",    "v_character"),
        ("Dev Traj.",    "v_dev_traj"),
        ("Production",   "v_production"),
        ("Durability",   "v_injury"),
    ]

    rows = []
    has_data = False
    for label, key in TRAITS:
        val = data.get(key)
        if val is not None:
            has_data = True
            bar_filled = min(10, max(0, int(round(float(val)))))
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            rows.append([label, bar, f"{val:.1f}"])
        else:
            rows.append([label, "░" * 10, "—"])

    if not has_data:
        return None

    t = Table(rows, colWidths=[1.1*inch, 1.8*inch, 0.4*inch])
    t.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, -1), "Courier"),
        ("FONTSIZE",    (0, 0), (-1, -1), 7),
        ("TEXTCOLOR",   (0, 0), (0, -1), C_MUTED),
        ("TEXTCOLOR",   (1, 0), (1, -1), C_ACCENT),
        ("TEXTCOLOR",   (2, 0), (2, -1), C_WHITE),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_BG, C_CARD]),
        ("TOPPADDING",  (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def generate_pdf(prospect_id: int, season_id: int = SEASON_ID) -> Path:
    """
    Main entry point — callable from Streamlit or CLI.
    Returns the Path of the generated PDF.
    """
    out_dir = PATHS.root / "exports" / "reports" / "pdf"
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        data = _fetch_prospect_data(conn, prospect_id, season_id)

    name_key  = _slugify(data.get("display_name") or str(prospect_id))
    date_str  = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename  = f"{prospect_id}_{name_key}_{date_str}.pdf"
    out_path  = out_dir / filename

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.5*inch,
        rightMargin=0.5*inch,
        topMargin=0.4*inch,
        bottomMargin=0.4*inch,
    )

    styles = getSampleStyleSheet()

    def style(name, **kwargs):
        return ParagraphStyle(name, parent=styles["Normal"], **kwargs)

    S_NAME      = style("name",      fontSize=20, textColor=C_WHITE,  leading=24, fontName="Helvetica-Bold")
    S_META      = style("meta",      fontSize=9,  textColor=C_MUTED,  leading=12)
    S_LABEL     = style("label",     fontSize=7,  textColor=C_MUTED,  leading=9,  fontName="Helvetica")
    S_SCORE     = style("score",     fontSize=28, textColor=C_ACCENT, leading=30, fontName="Helvetica-Bold")
    S_SCORE2    = style("score2",    fontSize=22, textColor=C_GOLD,   leading=26, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    S_SECTION   = style("section",   fontSize=7,  textColor=C_MUTED,  leading=10, fontName="Helvetica", spaceAfter=2)
    S_BODY      = style("body",      fontSize=8,  textColor=C_WHITE,  leading=11)
    S_STRENGTH  = style("strength",  fontSize=8,  textColor=C_GREEN,  leading=11)
    S_REDFLAG   = style("redflag",   fontSize=8,  textColor=C_RED,    leading=11)
    S_PENDING   = style("pending",   fontSize=9,  textColor=C_MUTED,  leading=12, alignment=TA_CENTER)

    story = []

    # ── HEADER ──────────────────────────────────────────────────────────────
    name        = data.get("display_name") or "Unknown"
    position    = data.get("position_group") or "—"
    school      = data.get("school_canonical") or "—"
    cons_rank   = data.get("consensus_rank")
    ras         = data.get("ras_total")
    apex_score  = data.get("apex_composite")
    rpg         = data.get("raw_score")
    apex_tier   = (data.get("apex_tier") or "").upper()
    archetype   = data.get("matched_archetype") or None
    fm_primary  = data.get("failure_mode_primary") or None
    cap_adj     = data.get("capital_adjusted") or data.get("capital_base") or None
    eval_conf   = data.get("eval_confidence") or None

    tier_color  = TIER_COLORS.get(apex_tier, C_MUTED)

    meta_parts = [f"#{cons_rank}" if cons_rank else "Unranked", school, position]
    if ras:
        meta_parts.append(f"RAS {ras:.2f}")

    header_data = [
        [Paragraph(name, S_NAME), "", Paragraph(f"{rpg:.1f}" if rpg else "—", S_SCORE)],
        [Paragraph(" · ".join(meta_parts), S_META), "", Paragraph(f"{apex_score:.1f}" if apex_score else "Pending APEX", S_SCORE2)],
        [
            Paragraph("PLAYER GRADE  |  DRAFT VALUE", S_LABEL),
            "",
            Paragraph(
                apex_tier if apex_tier else "",
                style("tier", fontSize=10, textColor=tier_color, fontName="Helvetica-Bold", alignment=TA_RIGHT)
            ),
        ],
    ]

    header_table = Table(header_data, colWidths=[4.5*inch, 0.5*inch, 2.0*inch])
    header_table.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("SPAN",        (0, 0), (1, 0)),
        ("SPAN",        (0, 1), (1, 1)),
        ("SPAN",        (0, 2), (1, 2)),
        ("LINEBELOW",   (0, 2), (-1, 2), 0.5, C_MUTED),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 6),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.08*inch))

    # ── ARCHETYPE + FM ROW ───────────────────────────────────────────────────
    arch_str = archetype if archetype else "Archetype Pending"
    fm_str   = fm_primary if fm_primary else ""
    pvc_note = f"RPG {rpg:.1f} × PVC {data.get('pvc', 1.0):.2f} = APEX {apex_score:.1f}" if (rpg and apex_score) else ""

    arch_data = [
        [
            Paragraph(f"<b>{arch_str}</b>", style("arch", fontSize=9, textColor=C_ACCENT if archetype else C_MUTED, leading=11)),
            Paragraph(f"<font color='#e05c5c'>{fm_str}</font>" if fm_str else "", style("fm", fontSize=9, textColor=C_FM_RED, leading=11)),
            Paragraph(pvc_note, style("pvc", fontSize=7, textColor=C_MUTED, leading=9, alignment=TA_RIGHT)),
        ]
    ]
    arch_table = Table(arch_data, colWidths=[2.8*inch, 2.0*inch, 2.2*inch])
    arch_table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE")]))
    story.append(arch_table)
    story.append(HRFlowable(width="100%", thickness=0.3, color=C_MUTED, spaceAfter=4))

    # ── TWO-COLUMN BODY ──────────────────────────────────────────────────────
    trait_table = _trait_bar_table(data)
    left_content = [trait_table] if trait_table else [Paragraph("Trait data pending APEX evaluation.", S_PENDING)]

    right_content = []

    # Signature play
    sig = data.get("signature_play")
    if sig:
        right_content.append(Paragraph("SIGNATURE PLAY", S_SECTION))
        right_content.append(Paragraph(sig, style("sig", fontSize=7.5, textColor=C_WHITE, leading=10)))
        right_content.append(Spacer(1, 0.06*inch))

    # Strengths (top 3)
    strengths_raw = data.get("strengths") or ""
    if strengths_raw.strip():
        right_content.append(Paragraph("STRENGTHS", S_SECTION))
        lines = [l.strip() for l in strengths_raw.split("\n") if l.strip()][:3]
        for line in lines:
            right_content.append(Paragraph(f"• {line}", S_STRENGTH))
        right_content.append(Spacer(1, 0.06*inch))

    # Red flags (top 3)
    red_raw = data.get("red_flags") or ""
    if red_raw.strip():
        right_content.append(Paragraph("RED FLAGS", S_SECTION))
        lines = [l.strip() for l in red_raw.split("\n") if l.strip()][:3]
        for line in lines:
            right_content.append(Paragraph(f"• {line}", S_REDFLAG))
        right_content.append(Spacer(1, 0.06*inch))

    if not (sig or strengths_raw.strip() or red_raw.strip()):
        right_content.append(Paragraph("Full evaluation pending.", S_PENDING))

    body_table = Table(
        [[left_content, right_content]],
        colWidths=[2.8*inch, 4.2*inch],
    )
    body_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEAFTER", (0, 0), (0, 0), 0.3, C_MUTED),
        ("LEFTPADDING",  (1, 0), (1, 0), 10),
    ]))
    story.append(body_table)
    story.append(HRFlowable(width="100%", thickness=0.3, color=C_MUTED, spaceBefore=4, spaceAfter=4))

    # ── TRANSLATION RISK ────────────────────────────────────────────────────
    trans = data.get("translation_risk")
    if trans:
        story.append(Paragraph("TRANSLATION RISK", S_SECTION))
        story.append(Paragraph(trans, style("trans", fontSize=7.5, textColor=C_MUTED, leading=10)))
        story.append(Spacer(1, 0.05*inch))

    # ── DRAFT CAPITAL + EVAL CONFIDENCE ─────────────────────────────────────
    if not cap_adj and cons_rank:
        if cons_rank <= 32:
            cap_fallback = "Day 1 capital (consensus-derived)"
        elif cons_rank <= 64:
            cap_fallback = "Day 2 Early capital (consensus-derived)"
        elif cons_rank <= 105:
            cap_fallback = "Day 2 Late capital (consensus-derived)"
        else:
            cap_fallback = "Day 3 capital (consensus-derived)"
    else:
        cap_fallback = cap_adj or "—"

    conf_str = f"Eval Confidence: {eval_conf}" if eval_conf else ""
    div_flag = data.get("divergence_flag")
    div_delta = data.get("divergence_rank_delta")
    div_str = ""
    if div_flag and div_delta is not None:
        sign = "+" if div_delta > 0 else ""
        div_str = f"Divergence: {div_flag} ({sign}{div_delta})"

    footer_data = [[
        Paragraph(f"<b>Draft Capital:</b> {cap_fallback}", style("cap", fontSize=8, textColor=C_WHITE, leading=10)),
        Paragraph(conf_str, style("conf", fontSize=8, textColor=C_MUTED, leading=10, alignment=TA_CENTER)),
        Paragraph(div_str, style("div", fontSize=8, textColor=C_ACCENT if div_flag else C_MUTED, leading=10, alignment=TA_RIGHT)),
    ]]
    footer_table = Table(footer_data, colWidths=[3.0*inch, 2.0*inch, 2.0*inch])
    footer_table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE")]))
    story.append(footer_table)

    # ── WATERMARK / FOOTER ───────────────────────────────────────────────────
    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph(
        f"DraftOS 2026 · Generated {date_str} · APEX {data.get('model_version', 'v2.3')}",
        style("wm", fontSize=6, textColor=C_MUTED, alignment=TA_CENTER)
    ))

    doc.build(story)
    print(f"  [PDF] Generated: {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DraftOS prospect one-pager PDF")
    parser.add_argument("--prospect-id", type=int, required=True)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    season_id = 1  # internal season_id for 2026
    path = generate_pdf(prospect_id=args.prospect_id, season_id=season_id)
    print(f"OK: PDF saved to {path}")


if __name__ == "__main__":
    main()
