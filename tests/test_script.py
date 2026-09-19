import json
import os

from funmirror.script import _load_state, _save_state


def test_load_state_missing_file_returns_empty_dict(tmp_path):
    assert _load_state(str(tmp_path / "nope.json")) == {}


def test_load_state_empty_path_returns_empty_dict():
    assert _load_state("") == {}


def test_save_and_load_state_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    _save_state(path, {}, {"repo1": "abc123"})

    assert _load_state(path) == {"repo1": "abc123"}


def test_save_state_merges_into_existing_entries(tmp_path):
    path = str(tmp_path / "nested" / "state.json")
    _save_state(path, {"repo1": "old"}, {"repo2": "new"})

    assert json.loads(open(path).read()) == {"repo1": "old", "repo2": "new"}


def test_save_state_noop_when_path_empty(tmp_path):
    _save_state("", {}, {"repo1": "abc123"})  # must not raise
    assert not os.path.exists(str(tmp_path / "state.json"))
