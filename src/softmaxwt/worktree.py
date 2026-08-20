import os
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from softmaxwt.graphite import GraphiteInfo, GraphiteStatus, fetch_all_graphite_info


def trunk_branch() -> str:
    """The trunk branch new worktrees start from and merge into ($WT_TRUNK_NAME)."""
    return os.environ.get("WT_TRUNK_NAME", "main")


@dataclass
class DiffStats:
    files: int
    insertions: int
    deletions: int


@dataclass
class Worktree:
    path: Path
    branch: str
    head: str

    @property
    def _query_cwd(self) -> Path:
        """Where to run branch/ref git queries. The worktree path when it exists,
        else the main repo root — branch state lives in shared refs, so these
        queries must keep working after the worktree directory is gone (a removed
        or never-created worktree); subprocess can't cd into a missing dir."""
        return self.path if self.path.exists() else git_root()

    def uncommitted_diff_stats(self) -> DiffStats | None:
        """Return diff stats or None if clean."""
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=self.path,
        )
        files = [line for line in status.stdout.strip().splitlines() if line]
        if not files:
            return None
        diff = subprocess.run(
            ["git", "diff", "--shortstat", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self.path,
        )
        insertions = deletions = 0
        for part in diff.stdout.split(","):
            part = part.strip()
            if "insertion" in part:
                insertions = int(part.split()[0])
            elif "deletion" in part:
                deletions = int(part.split()[0])
        return DiffStats(files=len(files), insertions=insertions, deletions=deletions)

    def unpushed_commits(self) -> list[str]:
        """Commit subjects on branch that aren't on its remote tracking branch."""
        result = subprocess.run(
            ["git", "log", "--oneline", f"{self.branch}@{{upstream}}..{self.branch}"],
            capture_output=True,
            text=True,
            cwd=self._query_cwd,
        )
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.strip().splitlines() if line]

    def has_no_upstream(self) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{self.branch}@{{upstream}}"],
            capture_output=True,
            cwd=self._query_cwd,
        )
        return result.returncode != 0

    def unmerged_commits(self) -> list[str]:
        """Commit subjects on branch not in the trunk (handles squash-merges too)."""
        if self._is_graphite_merged():
            return []
        result = subprocess.run(
            ["git", "log", "--oneline", f"origin/{trunk_branch()}..{self.branch}"],
            capture_output=True,
            text=True,
            cwd=self._query_cwd,
        )
        if result.returncode != 0:
            return []
        commits = [line for line in result.stdout.strip().splitlines() if line]
        if commits and self._is_squash_merged():
            return []
        return commits

    def _is_graphite_merged(self) -> bool:
        """Check if graphite considers this branch merged (handles merge queue squash-merges)."""
        info = self.graphite_info
        return info is not None and info.status == GraphiteStatus.merged

    def _is_squash_merged(self) -> bool:
        """Check if branch content is already in the trunk (tree comparison fallback)."""
        tree_result = subprocess.run(
            ["git", "merge-tree", "--write-tree", f"origin/{trunk_branch()}", self.branch],
            capture_output=True,
            text=True,
            cwd=self._query_cwd,
        )
        if tree_result.returncode != 0:
            return False
        merged_tree = tree_result.stdout.strip().splitlines()[0]
        main_tree = subprocess.run(
            ["git", "rev-parse", f"origin/{trunk_branch()}^{{tree}}"],
            capture_output=True,
            text=True,
            cwd=self._query_cwd,
        )
        if main_tree.returncode != 0:
            return False
        return merged_tree == main_tree.stdout.strip()

    @cached_property
    def graphite_info(self) -> GraphiteInfo | None:
        """Graphite PR status and URL, or None if untracked. Cached per instance."""
        return fetch_all_graphite_info().get(self.branch)

    def set_graphite_info(self, info: GraphiteInfo | None) -> None:
        """Prime the per-instance cache from a batch fetch (see fetch_all_graphite_info)."""
        self.__dict__["graphite_info"] = info

    def is_disposable(self) -> bool:
        """True when destroying loses nothing: clean tree, and either the PR is
        merged or there are no local-only commits (no PR ever existed counts)."""
        if self.path.exists() and self.uncommitted_diff_stats() is not None:
            return False
        info = self.graphite_info
        if info is not None and info.status == GraphiteStatus.merged:
            return True
        if self.unmerged_commits():
            return False
        return True


def git_root() -> Path:
    """Return the main repo root, even when invoked from inside a worktree."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    result.check_returncode()
    return Path(result.stdout.strip()).absolute().parent


def current_worktree_name() -> str | None:
    """Name of the worktree the cwd is inside (any depth), or None."""
    cwd = Path.cwd()
    return next(
        (parent.name for parent in (cwd, *cwd.parents) if parent.parent.name == ".worktrees"),
        None,
    )


def find_worktree(name: str) -> Worktree | None:
    """Look up a worktree by directory name, returning None if not found."""
    for wt in list_worktrees():
        if wt.path.name == name:
            return wt
    return None


def branch_exists(branch: str) -> bool:
    """True if a local branch by this name exists in the repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True,
        cwd=git_root(),
    )
    return result.returncode == 0


def list_worktrees() -> list[Worktree]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    result.check_returncode()

    def _is_linked(path: Path) -> bool:
        """Main worktree has .git dir; linked worktrees have a .git file."""
        return not (path / ".git").is_dir()

    worktrees: list[Worktree] = []
    path: Path | None = None
    head: str | None = None
    branch: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line.startswith("HEAD "):
            head = line.removeprefix("HEAD ")
        elif line.startswith("branch "):
            branch = line.removeprefix("branch refs/heads/")
        elif line == "":
            if path and head and branch and _is_linked(path):
                worktrees.append(Worktree(path=path, branch=branch, head=head))
            path = head = branch = None

    # Flush last entry (porcelain output may not end with blank line).
    if path and head and branch and _is_linked(path):
        worktrees.append(Worktree(path=path, branch=branch, head=head))

    return worktrees


def complete_worktree_name(incomplete: str) -> list[str]:
    return [wt.path.name for wt in list_worktrees() if wt.path.name.startswith(incomplete)]
