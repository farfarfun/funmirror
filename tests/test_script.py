import json
import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from funmirror.script import _load_state, _save_state, app

runner = CliRunner()


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

    assert json.loads(Path(path).read_text()) == {
        "gitee/org": {
            "repo1": {"src_sha": "old", "dst_sha": "old"},
            "repo2": {"src_sha": "new", "dst_sha": "new"},
        }
    }


def test_save_state_keeps_other_namespaces_untouched(tmp_path):
    path = str(tmp_path / "state.json")
    _save_state(path, "gitee/org", {"repo1": {"src_sha": "gitee-sha", "dst_sha": "gitee-sha"}})
    _save_state(path, "gitlab/org", {"repo1": {"src_sha": "gitlab-sha", "dst_sha": "gitlab-sha"}})

    data = json.loads(Path(path).read_text())
    assert data["gitee/org"]["repo1"]["src_sha"] == "gitee-sha"
    assert data["gitlab/org"]["repo1"]["src_sha"] == "gitlab-sha"


def test_save_state_noop_when_path_empty(tmp_path):
    _save_state("", "gitee/org", {"repo1": {"src_sha": "abc123"}})  # must not raise
    assert not os.path.exists(str(tmp_path / "state.json"))


def test_cli_help_lists_mirror_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "mirror" in result.output


def test_mirror_cli_preserves_options_and_defaults():
    with patch("funmirror.script._mirror", return_value=0) as mirror:
        result = runner.invoke(
            app,
            [
                "mirror",
                "--src-platform",
                "github",
                "--dst-platform",
                "gitee",
                "--src-org",
                "source",
                "--dst-org",
                "destination",
                "--src-token",
                "source-token",
                "--dst-token",
                "destination-token",
                "--src-key-file",
                "source-key",
                "--dst-key-file",
                "destination-key",
                "--src-endpoint",
                "https://source.example",
                "--dst-endpoint",
                "https://destination.example",
                "--repo-names",
                "one,two",
                "--workers",
                "2",
                "--detect-workers",
                "4",
                "--no-force",
                "--state-file",
                "state.json",
                "--incremental",
            ],
        )

    assert result.exit_code == 0
    mirror.assert_called_once_with(
        src_platform="github",
        dst_platform="gitee",
        src_org="source",
        dst_org="destination",
        src_token="source-token",
        dst_token="destination-token",
        src_key_file="source-key",
        dst_key_file="destination-key",
        src_endpoint="https://source.example",
        dst_endpoint="https://destination.example",
        repo_names="one,two",
        workers=2,
        detect_workers=4,
        force=False,
        state_file="state.json",
        incremental=True,
    )


def test_mirror_cli_returns_sync_failure_exit_code():
    with patch("funmirror.script._mirror", return_value=1) as mirror:
        result = runner.invoke(
            app,
            [
                "mirror",
                "--src-platform",
                "github",
                "--dst-platform",
                "gitee",
                "--src-org",
                "source",
                "--dst-org",
                "destination",
            ],
        )

    assert result.exit_code == 1
    assert mirror.call_args.kwargs["force"] is True
    assert mirror.call_args.kwargs["workers"] == 8


def test_mirror_cli_rejects_unknown_platform():
    result = runner.invoke(
        app,
        [
            "mirror",
            "--src-platform",
            "unknown",
            "--dst-platform",
            "gitee",
            "--src-org",
            "source",
            "--dst-org",
            "destination",
        ],
    )

    assert result.exit_code == 2
    assert "must be one of" in result.output
