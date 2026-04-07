# ── app.py wiring patch — swap _build_detail_html for draftos_detail_iframe_v2 ──
#
# 1. ADD this import near the top of app.py (with the other scripts imports):
#
from scripts.draftos_detail_iframe_v2 import build_detail_html, estimate_height
#
#
# 2. REPLACE _render_apex_detail() in app.py with this:
#
def _render_apex_detail(d: dict) -> None:
    """DraftOS Prospect Detail — iframe-isolated, full reference drawer treatment."""

    archetype_raw = d.get("matched_archetype") or d.get("apex_archetype") or ""

    comps_list   = []
    rate_info    = None
    fm_ref_comps = []

    if archetype_raw:
        try:
            with connect() as _hconn:
                comps_list   = get_historical_comps(_hconn, archetype_raw, limit=2)
                rate_info    = get_archetype_translation_rate(_hconn, archetype_raw)
        except Exception:
            comps_list = []
            rate_info  = None

    # FM reference records — fetch for each active FM code
    fm_codes_for_ref = set()
    for fv in [d.get("failure_mode_primary"), d.get("failure_mode_secondary")]:
        if fv and str(fv).strip().upper() not in ("", "NONE", "N/A"):
            import re as _re
            m = _re.search(r"FM-(\d+)", str(fv))
            if m:
                fm_codes_for_ref.add(int(m.group(1)))

    if fm_codes_for_ref:
        try:
            with connect() as _hconn:
                for code in sorted(fm_codes_for_ref):
                    refs = get_fm_reference_comps(_hconn, fm_code=f"FM-{code}", limit=2)
                    fm_ref_comps.extend(refs)
        except Exception:
            fm_ref_comps = []

    html_content = build_detail_html(d, comps_list, rate_info, fm_ref_comps or None)
    h = estimate_height(d, comps_list)

    components.html(html_content, height=h, scrolling=True)
#
#
# 3. DELETE the old _build_detail_html() function entirely (lines ~1632–2273 in app.py).
#    It is fully replaced by build_detail_html() in draftos_detail_iframe_v2.py.
#    _render_apex_detail() no longer calls it.
