import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from softmaxwt.claude import list_claude_agents

# Trimmed real `claude agents --json` output. Background agents carry `state`
# and may have no pid/status; interactive sessions carry `status`. Extra fields
# like startedAt must be ignored.
AGENTS_JSON = json.dumps(
    [
        {
            "id": "859cd8a3",
            "cwd": "/repo/.worktrees/foo",
            "kind": "background",
            "startedAt": 1780641852371,
            "sessionId": "859cd8a3-b77f-4ec6-a697-a4c502cd0a0e",
            "name": "Improve settings",
            "state": "blocked",
        },
        {
            "pid": 61700,
            "cwd": "/repo/.worktrees/foo/subdir",
            "kind": "interactive",
            "startedAt": 1781048266111,
            "sessionId": "6930153f-2624-4e20-9eab-50429655c786",
            "status": "busy",
        },
        {
            "pid": 61701,
            "cwd": "/repo/.worktrees/bar",
            "kind": "interactive",
            "sessionId": "7930153f-2624-4e20-9eab-504296551111",
            "status": "waiting",
        },
        {
            "pid": 61702,
            "cwd": "/repo/.worktrees/bar",
            "kind": "interactive",
            "sessionId": "8930153f-2624-4e20-9eab-504296552222",
            "status": "idle",
        },
    ]
)


def test_list_claude_agents_parses_json():
    mock_result = MagicMock(returncode=0, stdout=AGENTS_JSON)
    with patch("softmaxwt.claude.shutil.which", return_value="/bin/claude"):
        with patch("softmaxwt.claude.subprocess.run", return_value=mock_result):
            agents = list_claude_agents()

    background, busy, waiting, idle = agents
    assert background.pid is None
    assert background.name == "Improve settings"
    assert background.activity == "blocked"
    assert busy.pid == 61700
    assert busy.name is None
    # A session in a subdirectory still belongs to the worktree.
    assert busy.is_inside(Path("/repo/.worktrees/foo"))
    assert not busy.is_inside(Path("/repo/.worktrees/bar"))

    # Meaningful work in progress blocks collection: running (busy, or a
    # working/blocked background agent) or stopped mid-task waiting on the
    # user. Only idling at rest doesn't.
    assert background.is_active
    assert busy.is_active
    assert waiting.is_active
    assert not idle.is_active


def test_list_claude_agents_empty_when_claude_missing():
    with patch("softmaxwt.claude.shutil.which", return_value=None):
        assert list_claude_agents() == []
