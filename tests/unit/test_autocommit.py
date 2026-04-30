"""Tests for Phase 71.3 — auto-commit-per-turn.

Scenarios covered:

* :mod:`cantrip.agent.auto_commit` primitives — touched-file
  collection, dirty-tree detection, pre-cantrip and agent commit
  shapes, fallback subject lines, build_commit_message body.
* ``handle_auto_commit`` slash command (toggle, on/off, error
  paths, no-op when already in target state).
* ``--no-auto-commit`` CLI flag plumbing.
* Conversation-loop integration: when the agent reports it
  touched a file, the post-turn hook stages and commits with a
  Cantrip co-author trailer; opt-out via
  ``state.git_auto_commit = False`` keeps the working tree dirty.
* Pre-cantrip dirty separation: a session that starts with dirty
  files commits them as ``chore(pre-cantrip): save in-progress
  work`` before the agent runs.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from cantrip.agent import auto_commit
from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Message, Response, Role, ToolCall
from tests.conftest import FakeProvider


@pytest.fixture
def tmp_git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal git repo with one initial commit.

    Sets ``user.email`` / ``user.name`` so commits don't fail in
    a test environment without a global git config, and disables
    ``commit.gpgsign`` so a host with a signing key configured
    doesn't hang the test on a passphrase prompt.
    """
    subprocess.run(
        ["git", "init", "--initial-branch=main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@cantrip.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Cantrip Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("# Initial\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--no-gpg-sign", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def _head_message(repo: pathlib.Path) -> str:
    """Return HEAD's full commit message for assertion."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _head_count(repo: pathlib.Path) -> int:
    """Return the total commit count on HEAD."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class TestPrimitives:
    def test_is_git_repo_for_real_repo(self, tmp_git_repo: pathlib.Path):
        assert auto_commit._is_git_repo(tmp_git_repo) is True

    def test_is_git_repo_for_non_repo(self, tmp_path: pathlib.Path):
        assert auto_commit._is_git_repo(tmp_path) is False

    def test_is_git_repo_for_missing_path(self, tmp_path: pathlib.Path):
        assert auto_commit._is_git_repo(tmp_path / "nope") is False

    def test_has_dirty_tree_clean(self, tmp_git_repo: pathlib.Path):
        assert auto_commit._has_dirty_tree(tmp_git_repo) is False

    def test_has_dirty_tree_modified(self, tmp_git_repo: pathlib.Path):
        (tmp_git_repo / "README.md").write_text("# Modified\n")
        assert auto_commit._has_dirty_tree(tmp_git_repo) is True

    def test_has_dirty_tree_untracked(self, tmp_git_repo: pathlib.Path):
        (tmp_git_repo / "new.py").write_text("print('hi')\n")
        assert auto_commit._has_dirty_tree(tmp_git_repo) is True


class TestCollectTouchedFiles:
    def test_picks_up_write_file(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "src/charm.py", "content": "x"},
                    )
                ],
            ),
        ]
        assert auto_commit.collect_touched_files(msgs) == ["src/charm.py"]

    def test_picks_up_edit_file_path_alias(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="edit_file",
                        arguments={"file_path": "metadata.yaml"},
                    )
                ],
            ),
        ]
        assert auto_commit.collect_touched_files(msgs) == ["metadata.yaml"]

    def test_multi_edit_extracts_each_edit_path(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="multi_edit",
                        arguments={
                            "edits": [
                                {"path": "a.py", "old": "x", "new": "y"},
                                {"file_path": "b.py", "old": "x", "new": "y"},
                            ]
                        },
                    )
                ],
            ),
        ]
        assert auto_commit.collect_touched_files(msgs) == ["a.py", "b.py"]

    def test_dedups_repeated_paths(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "src/charm.py"},
                    ),
                    ToolCall(
                        id="c2",
                        name="edit_file",
                        arguments={"path": "src/charm.py"},
                    ),
                ],
            ),
        ]
        assert auto_commit.collect_touched_files(msgs) == ["src/charm.py"]

    def test_ignores_non_mutating_tools(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="read_file", arguments={"path": "x.py"}),
                    ToolCall(id="c2", name="git_status", arguments={}),
                ],
            ),
        ]
        assert auto_commit.collect_touched_files(msgs) == []

    def test_ignores_non_assistant_messages(self):
        msgs = [
            Message(role=Role.USER, content="do x"),
            Message(role=Role.TOOL, content="ok"),
        ]
        assert auto_commit.collect_touched_files(msgs) == []


class TestBuildCommitMessage:
    def test_uses_summary_subject_when_given(self):
        msg = auto_commit.build_commit_message(
            "fix the auth bug",
            summary="fix(auth): tighten session validation",
            files=["src/charm.py"],
        )
        assert msg.startswith("fix(auth): tighten session validation\n")
        assert "Co-Authored-By: Cantrip" in msg
        assert "src/charm.py" in msg

    def test_falls_back_to_user_message_subject(self):
        msg = auto_commit.build_commit_message("fix the auth bug")
        assert msg.startswith("agent: fix the auth bug\n")
        assert "Co-Authored-By: Cantrip" in msg

    def test_truncates_long_subject(self):
        long = "this is a very long summary " * 5
        msg = auto_commit.build_commit_message("x", summary=long, files=None)
        # First line is the subject; should be ≤ 72 chars.
        first = msg.splitlines()[0]
        assert len(first) <= 72

    def test_truncates_long_file_list(self):
        files = [f"file_{i}.py" for i in range(40)]
        msg = auto_commit.build_commit_message("do x", files=files)
        # Truncation marker present.
        assert "and 20 more" in msg

    def test_human_trailer_appended_after_cantrip(self):
        msg = auto_commit.build_commit_message(
            "do x",
            human_trailer="Co-Authored-By: Alice <alice@example.com>",
        )
        lines = msg.splitlines()
        # Cantrip trailer comes first, then the human trailer.
        cantrip_idx = next(
            i for i, line in enumerate(lines) if line.startswith("Co-Authored-By: Cantrip")
        )
        human_idx = next(
            i for i, line in enumerate(lines) if line.startswith("Co-Authored-By: Alice")
        )
        assert cantrip_idx < human_idx
        assert lines[human_idx] == "Co-Authored-By: Alice <alice@example.com>"

    def test_no_human_trailer_when_none(self):
        msg = auto_commit.build_commit_message("do x")
        coauthor_lines = [line for line in msg.splitlines() if line.startswith("Co-Authored-By:")]
        assert len(coauthor_lines) == 1
        assert "Cantrip" in coauthor_lines[0]


class TestHumanCoauthorTrailer:
    """Phase 51b.3 — human co-author trailer derivation from git config."""

    def test_returns_trailer_when_git_config_set(self, tmp_git_repo: pathlib.Path):
        # The fixture sets user.name=Cantrip Test, user.email=test@cantrip.local —
        # neither matches Cantrip's canonical, so we expect a trailer.
        trailer = auto_commit._human_coauthor_trailer(tmp_git_repo)
        assert trailer == "Co-Authored-By: Cantrip Test <test@cantrip.local>"

    def test_returns_none_when_git_config_unset(
        self,
        tmp_git_repo: pathlib.Path,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # Unset the local repo identity, then isolate from any global / system
        # config so the helper genuinely sees "no user configured anywhere".
        subprocess.run(["git", "config", "--unset", "user.name"], cwd=tmp_git_repo, check=True)
        subprocess.run(["git", "config", "--unset", "user.email"], cwd=tmp_git_repo, check=True)
        empty_global = tmp_path / "empty_gitconfig"
        empty_global.write_text("")
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_global))
        monkeypatch.setenv("HOME", str(tmp_path / "isolated_home"))
        assert auto_commit._human_coauthor_trailer(tmp_git_repo) is None

    def test_returns_none_when_email_matches_cantrip_canonical(self, tmp_git_repo: pathlib.Path):
        subprocess.run(
            ["git", "config", "user.email", auto_commit._CANTRIP_EMAIL],
            cwd=tmp_git_repo,
            check=True,
        )
        assert auto_commit._human_coauthor_trailer(tmp_git_repo) is None

    def test_returns_none_when_name_matches_cantrip_canonical(self, tmp_git_repo: pathlib.Path):
        subprocess.run(
            ["git", "config", "user.name", auto_commit._CANTRIP_NAME],
            cwd=tmp_git_repo,
            check=True,
        )
        assert auto_commit._human_coauthor_trailer(tmp_git_repo) is None

    def test_email_match_is_case_insensitive(self, tmp_git_repo: pathlib.Path):
        subprocess.run(
            ["git", "config", "user.email", auto_commit._CANTRIP_EMAIL.upper()],
            cwd=tmp_git_repo,
            check=True,
        )
        assert auto_commit._human_coauthor_trailer(tmp_git_repo) is None

    def test_post_turn_commit_includes_human_trailer(self, tmp_git_repo: pathlib.Path):
        """End-to-end: agent commit carries both trailers when git config is set."""
        (tmp_git_repo / "src").mkdir()
        (tmp_git_repo / "src" / "charm.py").write_text("# new\n")
        msgs = [
            Message(role=Role.USER, content="add a charm"),
            Message(
                role=Role.ASSISTANT,
                content="done",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "src/charm.py"},
                    )
                ],
            ),
        ]
        sha = auto_commit.post_turn_commit_agent_edits(tmp_git_repo, msgs, "add a charm")
        assert sha is not None
        body = _head_message(tmp_git_repo)
        coauthor_lines = [line for line in body.splitlines() if line.startswith("Co-Authored-By:")]
        assert len(coauthor_lines) == 2
        assert any(
            "Cantrip <" in line and auto_commit._CANTRIP_EMAIL in line for line in coauthor_lines
        )
        assert any("Cantrip Test <test@cantrip.local>" in line for line in coauthor_lines)

    def test_post_turn_commit_skips_human_trailer_when_email_matches_cantrip(
        self, tmp_git_repo: pathlib.Path
    ):
        """No duplicate trailer when the local git identity is Cantrip itself."""
        subprocess.run(
            ["git", "config", "user.email", auto_commit._CANTRIP_EMAIL],
            cwd=tmp_git_repo,
            check=True,
        )
        (tmp_git_repo / "src").mkdir()
        (tmp_git_repo / "src" / "charm.py").write_text("# new\n")
        msgs = [
            Message(role=Role.USER, content="add a charm"),
            Message(
                role=Role.ASSISTANT,
                content="done",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "src/charm.py"},
                    )
                ],
            ),
        ]
        sha = auto_commit.post_turn_commit_agent_edits(tmp_git_repo, msgs, "add a charm")
        assert sha is not None
        body = _head_message(tmp_git_repo)
        coauthor_lines = [line for line in body.splitlines() if line.startswith("Co-Authored-By:")]
        assert len(coauthor_lines) == 1


# ---------------------------------------------------------------------------
# pre/post-turn primitives end-to-end
# ---------------------------------------------------------------------------


class TestPreTurnCommitDirty:
    def test_no_op_when_clean(self, tmp_git_repo: pathlib.Path):
        sha = auto_commit.pre_turn_commit_dirty(tmp_git_repo)
        assert sha is None
        assert _head_count(tmp_git_repo) == 1

    def test_commits_modified_file(self, tmp_git_repo: pathlib.Path):
        (tmp_git_repo / "README.md").write_text("# Modified\n")
        sha = auto_commit.pre_turn_commit_dirty(tmp_git_repo)
        assert sha is not None
        assert _head_count(tmp_git_repo) == 2
        assert "chore(pre-cantrip)" in _head_message(tmp_git_repo)

    def test_commits_untracked_file(self, tmp_git_repo: pathlib.Path):
        (tmp_git_repo / "new.py").write_text("x = 1\n")
        sha = auto_commit.pre_turn_commit_dirty(tmp_git_repo)
        assert sha is not None
        assert "chore(pre-cantrip)" in _head_message(tmp_git_repo)

    def test_no_op_for_non_repo(self, tmp_path: pathlib.Path):
        sha = auto_commit.pre_turn_commit_dirty(tmp_path)
        assert sha is None

    def test_no_op_for_none_path(self):
        assert auto_commit.pre_turn_commit_dirty(None) is None


class TestPostTurnCommit:
    def test_commits_agent_edits(self, tmp_git_repo: pathlib.Path):
        # Simulate the agent writing a file.
        (tmp_git_repo / "src").mkdir()
        (tmp_git_repo / "src" / "charm.py").write_text("# new\n")

        msgs = [
            Message(role=Role.USER, content="add a charm"),
            Message(
                role=Role.ASSISTANT,
                content="done",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "src/charm.py"},
                    )
                ],
            ),
        ]
        sha = auto_commit.post_turn_commit_agent_edits(tmp_git_repo, msgs, "add a charm")
        assert sha is not None
        assert _head_count(tmp_git_repo) == 2
        body = _head_message(tmp_git_repo)
        assert "Co-Authored-By: Cantrip" in body
        assert "src/charm.py" in body

    def test_uses_provided_summary(self, tmp_git_repo: pathlib.Path):
        (tmp_git_repo / "x.py").write_text("x = 1\n")
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "x.py"})],
            )
        ]
        sha = auto_commit.post_turn_commit_agent_edits(
            tmp_git_repo, msgs, "do x", summary="feat(x): add module"
        )
        assert sha is not None
        first_line = _head_message(tmp_git_repo).splitlines()[0]
        assert first_line == "feat(x): add module"

    def test_no_op_when_no_files_touched(self, tmp_git_repo: pathlib.Path):
        msgs = [Message(role=Role.USER, content="hi")]
        sha = auto_commit.post_turn_commit_agent_edits(tmp_git_repo, msgs, "hi")
        assert sha is None
        assert _head_count(tmp_git_repo) == 1

    def test_no_op_for_non_repo(self, tmp_path: pathlib.Path):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "x.py"})],
            )
        ]
        sha = auto_commit.post_turn_commit_agent_edits(tmp_path, msgs, "x")
        assert sha is None

    def test_no_op_when_path_does_not_exist(self, tmp_git_repo: pathlib.Path):
        # Tool reported a path but the file isn't in the working tree.
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "ghost.py"})],
            )
        ]
        sha = auto_commit.post_turn_commit_agent_edits(tmp_git_repo, msgs, "ghost")
        # ``git add`` of a non-existent path errors; we return None.
        assert sha is None


# ---------------------------------------------------------------------------
# /auto-commit slash command
# ---------------------------------------------------------------------------


class TestAutoCommitSlash:
    def test_default_is_on(self):
        agent = CantripAgent(provider=FakeProvider())
        assert agent.state.git_auto_commit is True

    def test_bare_toggles(self):
        agent = CantripAgent(provider=FakeProvider())
        result = slash_commands.handle_auto_commit(agent, "")
        assert agent.state.git_auto_commit is False
        assert "off" in result.lower()
        result = slash_commands.handle_auto_commit(agent, "")
        assert agent.state.git_auto_commit is True
        assert "on" in result.lower()

    def test_explicit_on_off(self):
        agent = CantripAgent(provider=FakeProvider())
        slash_commands.handle_auto_commit(agent, "off")
        assert agent.state.git_auto_commit is False
        slash_commands.handle_auto_commit(agent, "on")
        assert agent.state.git_auto_commit is True

    def test_already_state_no_op(self):
        agent = CantripAgent(provider=FakeProvider())
        # Default is on → "on" again is a no-op.
        result = slash_commands.handle_auto_commit(agent, "on")
        assert "already on" in result.lower()

    def test_bad_argument(self):
        agent = CantripAgent(provider=FakeProvider())
        result = slash_commands.handle_auto_commit(agent, "yeah nah")
        assert result.startswith("Usage:")


# ---------------------------------------------------------------------------
# CLI flag plumbing
# ---------------------------------------------------------------------------


class TestNoAutoCommitFlag:
    def test_flag_defaults_to_false(self, monkeypatch: pytest.MonkeyPatch):
        import sys

        monkeypatch.setattr(sys, "argv", ["cantrip", "run", "."])
        from cantrip.main import parse_args

        ns = parse_args()
        assert ns.no_auto_commit is False

    def test_flag_parses(self, monkeypatch: pytest.MonkeyPatch):
        import sys

        monkeypatch.setattr(sys, "argv", ["cantrip", "run", "--no-auto-commit", "."])
        from cantrip.main import parse_args

        ns = parse_args()
        assert ns.no_auto_commit is True


# ---------------------------------------------------------------------------
# End-to-end: agent loop fires the auto-commit hook
# ---------------------------------------------------------------------------


class TestAgentLoopAutoCommits:
    @pytest.mark.asyncio
    async def test_post_turn_commit_runs_when_files_touched(self, tmp_git_repo: pathlib.Path):
        # The fake provider returns one tool call (write_file).  We
        # don't actually execute the tool — instead we manually
        # populate ``state.messages`` with the assistant message
        # and write the file ourselves.  The post-turn hook is
        # invoked directly to keep the test fast and focused.
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_git_repo)
        agent.state.messages.append(Message(role=Role.USER, content="add x"))
        (tmp_git_repo / "x.py").write_text("x = 1\n")
        agent.state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content="ok",
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "x.py"})],
            )
        )

        await agent._maybe_post_turn_commit_agent_edits("add x", turn_start_idx=0)

        assert _head_count(tmp_git_repo) == 2
        assert "Co-Authored-By: Cantrip" in _head_message(tmp_git_repo)
        assert agent.state.last_cantrip_commit_sha is not None

    @pytest.mark.asyncio
    async def test_opt_out_skips_commit(self, tmp_git_repo: pathlib.Path):
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_git_repo)
        agent.state.git_auto_commit = False

        agent.state.messages.append(Message(role=Role.USER, content="add x"))
        (tmp_git_repo / "x.py").write_text("x = 1\n")
        agent.state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content="ok",
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "x.py"})],
            )
        )

        await agent._maybe_post_turn_commit_agent_edits("add x", turn_start_idx=0)

        assert _head_count(tmp_git_repo) == 1
        assert agent.state.last_cantrip_commit_sha is None

    @pytest.mark.asyncio
    async def test_summariser_used_when_light_provider_present(self, tmp_git_repo: pathlib.Path):
        light = FakeProvider(responses=[Response(content="feat(x): add module")])
        agent = CantripAgent(
            provider=FakeProvider(),
            charm_path=tmp_git_repo,
            light_provider=light,
        )

        agent.state.messages.append(Message(role=Role.USER, content="add x"))
        (tmp_git_repo / "x.py").write_text("x = 1\n")
        agent.state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content="ok",
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "x.py"})],
            )
        )

        await agent._maybe_post_turn_commit_agent_edits("add x", turn_start_idx=0)

        first_line = _head_message(tmp_git_repo).splitlines()[0]
        assert first_line == "feat(x): add module"

    def test_pre_turn_dirty_commit_runs(self, tmp_git_repo: pathlib.Path):
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_git_repo)
        # Dirty the tree.
        (tmp_git_repo / "README.md").write_text("# Modified\n")
        # Drive the helper directly — the real conversation loop
        # would invoke this from inside ``_run_conversation_loop``.
        agent._maybe_pre_turn_commit_dirty()

        assert _head_count(tmp_git_repo) == 2
        assert "chore(pre-cantrip)" in _head_message(tmp_git_repo)

    def test_pre_turn_dirty_no_op_when_disabled(self, tmp_git_repo: pathlib.Path):
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_git_repo)
        agent.state.git_auto_commit = False
        (tmp_git_repo / "README.md").write_text("# Modified\n")
        agent._maybe_pre_turn_commit_dirty()
        assert _head_count(tmp_git_repo) == 1
