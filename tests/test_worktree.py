import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from softmaxwt.graphite import GraphiteStatus, fetch_all_graphite_info
from softmaxwt.worktree import git_root, list_worktrees

PORCELAIN_OUTPUT = """\
worktree /repo
HEAD abc1234567890
branch refs/heads/main

worktree /repo/.worktrees/foo
HEAD def4567890123
branch refs/heads/wt/foo

"""


def test_list_worktrees_parses_porcelain():
    mock_result = MagicMock(stdout=PORCELAIN_OUTPUT)
    with patch("softmaxwt.worktree.subprocess.run", return_value=mock_result):
        wts = list_worktrees()

    assert len(wts) == 2
    assert wts[0].path == Path("/repo")
    assert wts[0].branch == "main"
    assert wts[0].head == "abc1234567890"
    assert wts[1].path == Path("/repo/.worktrees/foo")
    assert wts[1].branch == "wt/foo"


PORCELAIN_NO_TRAILING_NEWLINE = """\
worktree /repo
HEAD aaa
branch refs/heads/main"""


def test_list_worktrees_no_trailing_blank_line():
    mock_result = MagicMock(stdout=PORCELAIN_NO_TRAILING_NEWLINE)
    with patch("softmaxwt.worktree.subprocess.run", return_value=mock_result):
        wts = list_worktrees()

    assert len(wts) == 1
    assert wts[0].branch == "main"


def test_git_root_returns_parent_of_common_dir():
    mock_result = MagicMock(stdout="/home/user/repo/.git\n")
    with patch("softmaxwt.worktree.subprocess.run", return_value=mock_result) as mock_run:
        root = git_root()

    assert root == Path("/home/user/repo")
    mock_run.assert_called_once_with(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )


def test_git_root_works_from_worktree():
    """--git-common-dir returns the main .git even from a linked worktree."""
    mock_result = MagicMock(stdout="/home/user/repo/.git\n")
    with patch("softmaxwt.worktree.subprocess.run", return_value=mock_result):
        root = git_root()

    # Should be the main repo root, not the worktree path.
    assert root == Path("/home/user/repo")


def _write_graphite_cache(git_dir: Path, tracked: list[str], pr_info: dict) -> None:
    """Lay down the two graphite cache files `fetch_all_graphite_info` reads."""
    con = sqlite3.connect(git_dir / ".graphite_metadata.db")
    con.execute("CREATE TABLE branch_metadata (branch_name TEXT)")
    con.executemany("INSERT INTO branch_metadata (branch_name) VALUES (?)", [(b,) for b in tracked])
    con.commit()
    con.close()
    (git_dir / ".graphite_pr_info").write_text(json.dumps(pr_info))


# Mirrors a real `.graphite_pr_info`: an open PR, a merged branch (state MERGED),
# and one queued to merge (status QUEUED_TO_MERGE). `no-pr-branch` and `main` are
# tracked but have no PR; `untracked-branch` is absent from branch_metadata.
PR_INFO = {
    "prInfos": [
        {
            "headRefName": "open-branch",
            "prNumber": 14454,
            "state": "OPEN",
            "url": "https://app.graphite.com/github/pr/Metta-AI/metta/14454",
        },
        {
            "headRefName": "merged-branch",
            "prNumber": 14430,
            "state": "MERGED",
            "url": "https://app.graphite.com/github/pr/Metta-AI/metta/14430",
        },
        {
            "headRefName": "merging-branch",
            "prNumber": 14460,
            "state": "OPEN",
            "url": "https://app.graphite.com/github/pr/Metta-AI/metta/14460",
        },
    ],
    "mergeabilityStatuses": [
        {"prNumber": 14454, "mergeabilityStatus": "OPEN"},
        {"prNumber": 14430, "mergeabilityStatus": "MERGED"},
        {"prNumber": 14460, "mergeabilityStatus": "QUEUED_TO_MERGE"},
    ],
}

TRACKED = ["main", "no-pr-branch", "open-branch", "merged-branch", "merging-branch"]


def test_fetch_all_graphite_info_reads_cache(tmp_path):
    _write_graphite_cache(tmp_path, TRACKED, PR_INFO)
    with patch("softmaxwt.graphite._git_common_dir", return_value=tmp_path):
        info = fetch_all_graphite_info()

    assert info["open-branch"].status == GraphiteStatus.open
    assert info["open-branch"].pr_url == "https://app.graphite.com/github/pr/Metta-AI/metta/14454"

    assert info["merged-branch"].status == GraphiteStatus.merged
    assert info["merged-branch"].pr_url == "https://app.graphite.com/github/pr/Metta-AI/metta/14430"

    # A PR enqueued in the merge queue reports as merging, not open.
    assert info["merging-branch"].status == GraphiteStatus.merging

    # Tracked-but-no-PR and trunk both classify as no_pr.
    assert info["no-pr-branch"].status == GraphiteStatus.no_pr
    assert info["no-pr-branch"].pr_url is None
    assert info["main"].status == GraphiteStatus.no_pr

    # Untracked branches are absent entirely.
    assert "untracked-branch" not in info


def test_fetch_all_graphite_info_empty_without_cache(tmp_path):
    """No graphite metadata db (graphite never ran here) -> empty, not a crash."""
    with patch("softmaxwt.graphite._git_common_dir", return_value=tmp_path):
        assert fetch_all_graphite_info() == {}
