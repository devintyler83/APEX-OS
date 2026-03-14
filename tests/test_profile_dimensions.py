"""Tests for Madden-style profile dimension mapping."""
from draftos.ui.profile_dimensions import get_profile_dimensions


def _make_traits(**overrides):
    """Build a complete traits dict with defaults, applying overrides."""
    base = {
        "v_processing": 7.0, "v_athleticism": 7.0, "v_scheme_vers": 7.0,
        "v_comp_tough": 7.0, "v_character": 7.0, "v_dev_traj": 7.0,
        "v_production": 7.0, "v_injury": 7.0,
        "c1_public_record": 7.0, "c2_motivation": 7.0, "c3_psych_profile": 7.0,
    }
    base.update(overrides)
    return base


def test_edge_returns_6_dimensions():
    dims = get_profile_dimensions("EDGE", _make_traits())
    assert len(dims) == 6
    labels = [d[0] for d in dims]
    assert "Speed Rush" in labels
    assert "Hand Technique" in labels
    assert "Motor" in labels


def test_qb_returns_6_dimensions():
    dims = get_profile_dimensions("QB", _make_traits())
    assert len(dims) == 6
    assert dims[1][0] == "Processing"  # QB processing is 2nd dimension


def test_safety_alias_fs():
    dims_s = get_profile_dimensions("S", _make_traits())
    dims_fs = get_profile_dimensions("FS", _make_traits())
    assert len(dims_s) == len(dims_fs)
    assert [d[0] for d in dims_s] == [d[0] for d in dims_fs]


def test_unknown_position_returns_empty():
    dims = get_profile_dimensions("PUNTER", _make_traits())
    assert dims == []


def test_direct_lookup_accuracy():
    traits = _make_traits(v_athleticism=9.2)
    dims = get_profile_dimensions("EDGE", traits)
    speed_rush = [d for d in dims if d[0] == "Speed Rush"][0]
    assert speed_rush[1] == 9.2  # direct lookup, should match exactly


def test_weighted_blend_accuracy():
    traits = _make_traits(v_athleticism=8.0, v_scheme_vers=6.0)
    dims = get_profile_dimensions("EDGE", traits)
    bend = [d for d in dims if d[0] == "Bend & Flexibility"][0]
    expected = round(8.0 * 0.6 + 6.0 * 0.4, 1)  # 7.2
    assert bend[1] == expected


def test_none_traits_default_to_zero():
    traits = {"v_processing": None, "v_athleticism": 8.0}
    # Clean None -> 0.0 as the app.py code does
    clean = {k: (float(v) if v is not None else 0.0) for k, v in traits.items()}
    dims = get_profile_dimensions("QB", clean)
    assert all(isinstance(d[1], float) for d in dims)
