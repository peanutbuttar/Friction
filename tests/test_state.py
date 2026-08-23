import json
import multiprocessing
from pathlib import Path

from friction import state as st


def test_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    s = st.load(p)
    s["passes"]["tier2:reddit.com"] = "2026-08-24T12:15:00"
    st.save(s, p)
    assert st.load(p)["passes"]["tier2:reddit.com"] == "2026-08-24T12:15:00"


def test_missing_file_gives_defaults(tmp_path):
    assert st.load(tmp_path / "nope.json") == st.DEFAULT_STATE


def test_corrupt_file_fails_closed_to_defaults(tmp_path):
    """A corrupt file must not crash the daemon, and must not read as 'unarmed'."""
    p = tmp_path / "state.json"
    p.write_text("{ this is not json")
    s = st.load(p)
    assert s == st.DEFAULT_STATE
    assert s["master_disarmed_until"] is None      # i.e. armed, not disarmed


def test_wrong_schema_version_gives_defaults(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 999, "master_disarmed_until": "2099-01-01T00:00:00"}))
    assert st.load(p)["master_disarmed_until"] is None


def test_partial_state_is_filled_in(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 1, "passes": {"a": "b"}}))
    s = st.load(p)
    assert s["passes"] == {"a": "b"}
    assert "manual_arms" in s and "master_disarmed_until" in s


def test_save_leaves_no_temp_files(tmp_path):
    p = tmp_path / "state.json"
    st.save(st.load(p), p)
    assert [f.name for f in tmp_path.iterdir()] == ["state.json"]


def test_update_applies_and_persists(tmp_path):
    p = tmp_path / "state.json"
    st.update(lambda s: s["passes"].update({"k": "v"}), p)
    assert st.load(p)["passes"]["k"] == "v"


def _bump(args):
    path, i = args
    st.update(lambda s: s["passes"].update({f"k{i}": str(i)}), Path(path))


def test_concurrent_updates_do_not_clobber(tmp_path):
    """Two processes toggling at once must both survive -- this is why we lock."""
    p = tmp_path / "state.json"
    st.save(st.load(p), p)
    with multiprocessing.Pool(4) as pool:
        pool.map(_bump, [(str(p), i) for i in range(12)])
    passes = st.load(p)["passes"]
    assert len(passes) == 12, f"lost writes: only {len(passes)}/12 survived"
