import json
import os

from funmirror.script import _load_state, _save_state


def test_load_state_missing_file_returns_empty_dict(tmp_path):
    assert _load_state(str(tmp_path / "nope.json"), "gitee/org") == {}


def test_load_state_empty_path_returns_empty_dict():
    assert _load_state("", "gitee/org") == {}


def test_save_and_load_state_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    _save_state(path, "gitee/org", {"repo1": {"src_sha": "abc123", "dst_sha": "abc123"}})

    assert _load_state(path, "gitee/org") == {
        "repo1": {"src_sha": "abc123", "dst_sha": "abc123"}
    }


def test_save_state_merges_into_existing_entries_in_same_namespace(tmp_path):
    path = str(tmp_path / "nested" / "state.json")
    _save_state(path, "gitee/org", {"repo1": {"src_sha": "old", "dst_sha": "old"}})
    _save_state(path, "gitee/org", {"repo2": {"src_sha": "new", "dst_sha": "new"}})

    assert json.loads(open(path).read()) == {
        "gitee/org": {
            "repo1": {"src_sha": "old", "dst_sha": "old"},
            "repo2": {"src_sha": "new", "dst_sha": "new"},
        }
    }


def test_save_state_keeps_other_namespaces_untouched(tmp_path):
    path = str(tmp_path / "state.json")
    _save_state(path, "gitee/org", {"repo1": {"src_sha": "gitee-sha", "dst_sha": "gitee-sha"}})
    _save_state(path, "gitlab/org", {"repo1": {"src_sha": "gitlab-sha", "dst_sha": "gitlab-sha"}})

    data = json.loads(open(path).read())
    assert data["gitee/org"]["repo1"]["src_sha"] == "gitee-sha"
    assert data["gitlab/org"]["repo1"]["src_sha"] == "gitlab-sha"


def test_save_state_noop_when_path_empty(tmp_path):
    _save_state("", "gitee/org", {"repo1": {"src_sha": "abc123"}})  # must not raise
    assert not os.path.exists(str(tmp_path / "state.json"))
