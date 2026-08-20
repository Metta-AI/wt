import sqlite3
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class GraphiteStatus(str, Enum):
    merged = "merged"
    merging = "merging"
    open = "open"
    no_pr = "no pr"


@dataclass
class GraphiteInfo:
    status: GraphiteStatus
    pr_url: str | None = None


# Graphite keeps its whole local state in the shared .git dir: which branches it
# tracks (the `branch_metadata` SQLite table) and the PR/merge status of each
# (`.graphite_pr_info`). `gt log` reads from exactly this cache — it makes no
# network call — so parsing the files reproduces what `gt log` prints while
# skipping the ~0.6s graphite subprocess. The format is graphite's private
# interface; if a `gt` upgrade changes it this parser is what needs updating.


class _PrInfo(BaseModel):
    headRefName: str
    prNumber: int
    state: str  # "OPEN" | "MERGED" | ...
    url: str | None = None


class _Mergeability(BaseModel):
    prNumber: int
    mergeabilityStatus: str  # "MERGED" | "QUEUED_TO_MERGE" | "DRAFT" | "OPEN" | ...


class _PrInfoFile(BaseModel):
    prInfos: list[_PrInfo] = []
    mergeabilityStatuses: list[_Mergeability] = []


def _git_common_dir() -> Path:
    """Absolute path to the shared .git dir, even from inside a linked worktree."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    result.check_returncode()
    return Path(result.stdout.strip()).absolute()


def _tracked_branches(git_dir: Path) -> set[str]:
    """Branch names graphite tracks, from its metadata SQLite cache."""
    db = git_dir / ".graphite_metadata.db"
    if not db.exists():
        return set()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("PRAGMA busy_timeout = 1000")  # graphite may be mid-write
    try:
        rows = con.execute("SELECT branch_name FROM branch_metadata").fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def _pr_info_by_branch(git_dir: Path) -> dict[str, GraphiteInfo]:
    """Per-branch PR status, parsed from graphite's `.graphite_pr_info` cache."""
    path = git_dir / ".graphite_pr_info"
    if not path.exists():
        return {}
    parsed = _PrInfoFile.model_validate_json(path.read_text())
    mergeability = {m.prNumber: m.mergeabilityStatus for m in parsed.mergeabilityStatuses}
    return {
        pr.headRefName: GraphiteInfo(
            status=_classify(pr, mergeability.get(pr.prNumber, "")),
            pr_url=pr.url,
        )
        for pr in parsed.prInfos
    }


def _classify(pr: _PrInfo, mergeability: str) -> GraphiteStatus:
    if pr.state == "MERGED" or mergeability == "MERGED":
        return GraphiteStatus.merged
    if "QUEUE" in mergeability or "MERGING" in mergeability:
        return GraphiteStatus.merging
    return GraphiteStatus.open


def fetch_all_graphite_info() -> dict[str, GraphiteInfo]:
    """Per-branch graphite info, keyed by branch name, read from the on-disk cache.

    Tracked branches without a PR map to `no_pr`; branches absent from the result
    are untracked by graphite. Replaces a per-worktree `gt branch info` (and the
    earlier single `gt log`) with plain file reads.
    """
    git_dir = _git_common_dir()
    tracked = _tracked_branches(git_dir)
    if not tracked:
        return {}
    pr_info = _pr_info_by_branch(git_dir)
    return {branch: pr_info.get(branch, GraphiteInfo(status=GraphiteStatus.no_pr)) for branch in tracked}
