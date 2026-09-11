"""Tests for user-defined slash commands (Phase 68.3)."""

from __future__ import annotations

import textwrap
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from cantrip.agent import queue as queue_module
from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.commands.custom import (
    CustomCommand,
    CustomCommandError,
    CustomCommandRegistry,
    discover_custom_commands,
    expand,
    load_command_file,
)
from cantrip.agent.permissions import (
    PermissionManager,
    PermissionOutcome,
    PermissionRule,
    PermissionRuleset,
)

if TYPE_CHECKING:
    import pathlib

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestLoadCommandFile:
    """Frontmatter + filename → :class:`CustomCommand`."""

    def test_valid_file(self, tmp_path: pathlib.Path):
        path = tmp_path / "relation-check.md"
        path.write_text(
            textwrap.dedent(
                """\
                ---
                description: Inspect a relation on a deployed charm
                agent: primary
                ---
                Inspect the ``$1`` relation on the live deployment.
                """
            )
        )
        command = load_command_file(path)
        assert command.verb == "/relation-check"
        assert command.description == "Inspect a relation on a deployed charm"
        assert command.agent == "primary"
        assert command.subtask is False
        assert command.model is None
        assert "$1" in command.body

    def test_body_without_frontmatter(self, tmp_path: pathlib.Path):
        path = tmp_path / "say-hi.md"
        path.write_text("Say hi to the user.")
        command = load_command_file(path)
        assert command.verb == "/say-hi"
        assert command.description.endswith("say-hi.md")  # fallback description
        assert command.body == "Say hi to the user."

    def test_subtask_true_routes_to_agent(self, tmp_path: pathlib.Path):
        path = tmp_path / "deep-dive.md"
        path.write_text(
            textwrap.dedent(
                """\
                ---
                description: Deep research under the research agent
                agent: research
                subtask: true
                ---
                Investigate ``$ARGUMENTS``.
                """
            )
        )
        command = load_command_file(path)
        assert command.subtask is True
        assert command.agent == "research"

    def test_unknown_frontmatter_key_raises(self, tmp_path: pathlib.Path):
        path = tmp_path / "bad.md"
        path.write_text("---\nmystery: yes\n---\nx")
        with pytest.raises(CustomCommandError) as exc:
            load_command_file(path)
        assert "unknown frontmatter keys" in str(exc.value)

    def test_invalid_filename_raises(self, tmp_path: pathlib.Path):
        path = tmp_path / "Bad Name.md"
        path.write_text("x")
        with pytest.raises(CustomCommandError) as exc:
            load_command_file(path)
        assert "invalid command name" in str(exc.value)

    def test_missing_closing_delimiter_raises(self, tmp_path: pathlib.Path):
        path = tmp_path / "broken.md"
        path.write_text("---\ndescription: x\nBody starts here\n")
        with pytest.raises(CustomCommandError):
            load_command_file(path)

    def test_empty_body_raises(self, tmp_path: pathlib.Path):
        path = tmp_path / "empty.md"
        path.write_text("---\ndescription: nothing\n---\n   \n")
        with pytest.raises(CustomCommandError):
            load_command_file(path)


class TestFrontmatterValidation:
    """Malformed frontmatter names the offending key, not a stack trace.

    A user hand-editing ``.cantrip/commands/*.md`` gets these messages
    with the file path prefixed, so each one has to be specific enough
    to point at the line they got wrong.
    """

    def _load(self, tmp_path: pathlib.Path, frontmatter: str) -> CustomCommand:
        path = tmp_path / "thing.md"
        path.write_text(f"---\n{frontmatter}\n---\nPrompt body.\n")
        return load_command_file(path)

    def _error(self, tmp_path: pathlib.Path, frontmatter: str) -> str:
        with pytest.raises(CustomCommandError) as exc:
            self._load(tmp_path, frontmatter)
        return str(exc.value)

    def test_unparseable_yaml(self, tmp_path: pathlib.Path):
        assert "invalid YAML frontmatter" in self._error(tmp_path, "description: [unclosed")

    def test_empty_frontmatter_is_treated_as_absent(self, tmp_path: pathlib.Path):
        command = self._load(tmp_path, "# just a comment")
        assert command.verb == "/thing"
        assert command.description == "User command from thing.md"

    def test_scalar_frontmatter_rejected(self, tmp_path: pathlib.Path):
        assert "must be a YAML mapping" in self._error(tmp_path, "just-a-string")

    def test_non_string_description_rejected(self, tmp_path: pathlib.Path):
        assert "'description' must be a string" in self._error(tmp_path, "description: 42")

    @pytest.mark.parametrize("value", ["agent: []", "agent: ''"])
    def test_empty_or_non_string_agent_rejected(self, tmp_path: pathlib.Path, value: str):
        assert "'agent' must be a non-empty string" in self._error(tmp_path, value)

    def test_non_string_model_rejected(self, tmp_path: pathlib.Path):
        assert "'model' must be a string or null" in self._error(tmp_path, "model: 3")

    def test_non_boolean_subtask_rejected(self, tmp_path: pathlib.Path):
        assert "'subtask' must be a boolean" in self._error(tmp_path, "subtask: maybe")


class TestDiscoverCustomCommands:
    """Layer precedence across user and repo directories."""

    def _write(self, dir_path: pathlib.Path, name: str, body: str) -> None:
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / name).write_text(body)

    def test_repo_beats_user(self, tmp_path: pathlib.Path):
        user_dir = tmp_path / "user"
        repo_root = tmp_path / "charm"
        self._write(
            user_dir / "commands",
            "test.md",
            "---\ndescription: user version\n---\nuser body",
        )
        self._write(
            repo_root / ".cantrip" / "commands",
            "test.md",
            "---\ndescription: repo version\n---\nrepo body",
        )
        commands = discover_custom_commands(charm_path=repo_root, user_config_dir=user_dir)
        assert len(commands) == 1
        assert commands[0].description == "repo version"
        assert commands[0].body == "repo body"

    def test_merges_unique_commands(self, tmp_path: pathlib.Path):
        user_dir = tmp_path / "user"
        repo_root = tmp_path / "charm"
        self._write(
            user_dir / "commands",
            "uonly.md",
            "---\ndescription: u\n---\nu",
        )
        self._write(
            repo_root / ".cantrip" / "commands",
            "ronly.md",
            "---\ndescription: r\n---\nr",
        )
        commands = discover_custom_commands(charm_path=repo_root, user_config_dir=user_dir)
        verbs = {c.verb for c in commands}
        assert verbs == {"/uonly", "/ronly"}

    def test_missing_dirs_yield_empty(self, tmp_path: pathlib.Path):
        assert (
            discover_custom_commands(
                charm_path=tmp_path / "nothing",
                user_config_dir=tmp_path / "also-nothing",
            )
            == []
        )

    def test_malformed_file_is_skipped(self, tmp_path: pathlib.Path):
        user_dir = tmp_path / "user"
        self._write(
            user_dir / "commands",
            "broken.md",
            "---\nmystery_key: 1\n---\nbody",
        )
        self._write(
            user_dir / "commands",
            "good.md",
            "---\ndescription: ok\n---\nbody",
        )
        commands = discover_custom_commands(charm_path=None, user_config_dir=user_dir)
        assert [c.verb for c in commands] == ["/good"]


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


def _make_command(body: str, agent: str = "primary") -> CustomCommand:
    return CustomCommand(
        verb="/sample",
        description="sample",
        body=body,
        agent=agent,
    )


class TestArgumentSubstitution:
    """``$ARGUMENTS`` and ``$1``/``$2``."""

    @pytest.mark.asyncio
    async def test_arguments_placeholder(self):
        out = await expand(_make_command("Arguments: $ARGUMENTS"), "hello world")
        assert out == "Arguments: hello world"

    @pytest.mark.asyncio
    async def test_positional_placeholders(self):
        out = await expand(
            _make_command("First: $1\nSecond: $2\nThird: $3"),
            "alpha beta",
        )
        # ``$3`` is unset — expands to an empty string.
        assert out == "First: alpha\nSecond: beta\nThird: "

    @pytest.mark.asyncio
    async def test_quoted_positional(self):
        out = await expand(
            _make_command("First: $1\nAll: $ARGUMENTS"),
            '"first arg" second',
        )
        assert "First: first arg" in out
        assert 'All: "first arg" second' in out


class TestFileReferences:
    """``@path`` substitution."""

    @pytest.mark.asyncio
    async def test_repo_local_file(self, tmp_path: pathlib.Path):
        (tmp_path / "notes.md").write_text("hello from file\n")
        out = await expand(
            _make_command("Notes:\n@notes.md"),
            "",
            repo_root=tmp_path,
        )
        assert "hello from file" in out

    @pytest.mark.asyncio
    async def test_absolute_path_rejected(self, tmp_path: pathlib.Path):
        (tmp_path / "a.md").write_text("x")
        with pytest.raises(CustomCommandError) as exc:
            await expand(
                _make_command(f"@{tmp_path / 'a.md'}"),
                "",
                repo_root=tmp_path,
            )
        assert "absolute paths" in str(exc.value)

    @pytest.mark.asyncio
    async def test_traversal_rejected(self, tmp_path: pathlib.Path):
        charm = tmp_path / "charm"
        charm.mkdir()
        (tmp_path / "outside.md").write_text("secret")
        with pytest.raises(CustomCommandError):
            await expand(
                _make_command("@../outside.md"),
                "",
                repo_root=charm,
            )

    @pytest.mark.asyncio
    async def test_missing_file_raises(self, tmp_path: pathlib.Path):
        with pytest.raises(CustomCommandError) as exc:
            await expand(
                _make_command("@missing.md"),
                "",
                repo_root=tmp_path,
            )
        assert "no such file" in str(exc.value)


class TestShellReferences:
    """``!`cmd` `` substitution routed through the permission gate."""

    @pytest.mark.asyncio
    async def test_allow_runs_the_shell(self, tmp_path: pathlib.Path):
        # No ruleset → default allow.
        out = await expand(
            _make_command("Output: !`echo hi`"),
            "",
            repo_root=tmp_path,
        )
        assert "Output: hi" in out

    @pytest.mark.asyncio
    async def test_deny_blocks_with_clear_error(self, tmp_path: pathlib.Path):
        ruleset = PermissionRuleset(bash=(PermissionRule("echo *", PermissionOutcome.DENY),))
        with pytest.raises(CustomCommandError) as exc:
            await expand(
                _make_command("Output: !`echo hi`"),
                "",
                repo_root=tmp_path,
                permissions=ruleset,
            )
        assert "refused by permissions policy" in str(exc.value)

    @pytest.mark.asyncio
    async def test_ask_uses_manager_when_approved(self, tmp_path: pathlib.Path):
        import asyncio

        ruleset = PermissionRuleset(bash=(PermissionRule("echo *", PermissionOutcome.ASK),))
        manager = PermissionManager(timeout_seconds=5.0)

        async def approve_soon() -> None:
            while not manager.pending:
                await asyncio.sleep(0)
            manager.resolve(manager.pending[0], approved=True)

        task = asyncio.create_task(approve_soon())
        out = await expand(
            _make_command("!`echo allowed`"),
            "",
            repo_root=tmp_path,
            permissions=ruleset,
            permission_manager=manager,
        )
        await task
        assert "allowed" in out

    @pytest.mark.asyncio
    async def test_ask_without_manager_errors(self, tmp_path: pathlib.Path):
        ruleset = PermissionRuleset(bash=(PermissionRule("echo *", PermissionOutcome.ASK),))
        with pytest.raises(CustomCommandError) as exc:
            await expand(
                _make_command("!`echo maybe`"),
                "",
                repo_root=tmp_path,
                permissions=ruleset,
                permission_manager=None,
            )
        assert "no interactive permission surface" in str(exc.value)

    @pytest.mark.asyncio
    async def test_failed_command_includes_exit_code(self, tmp_path: pathlib.Path):
        out = await expand(
            _make_command("Result:\n!`sh -c 'echo err >&2; exit 2'`"),
            "",
            repo_root=tmp_path,
        )
        assert "[exit 2]" in out
        assert "[stderr]" in out
        assert "err" in out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_get_by_verb(self):
        cmd = CustomCommand(verb="/a", description="x", body="b")
        reg = CustomCommandRegistry(commands=(cmd,))
        assert reg.get("/a") is cmd
        assert reg.get("/missing") is None

    def test_verbs_preserves_order(self):
        cmds = (
            CustomCommand(verb="/a", description="x", body="b"),
            CustomCommand(verb="/b", description="x", body="b"),
        )
        reg = CustomCommandRegistry(commands=cmds)
        assert reg.verbs == ("/a", "/b")

    def test_to_mapping_returns_dict(self):
        cmds = (
            CustomCommand(verb="/a", description="x", body="b"),
            CustomCommand(verb="/b", description="x", body="b"),
        )
        reg = CustomCommandRegistry(commands=cmds)
        mapping = reg.to_mapping()
        assert set(mapping.keys()) == {"/a", "/b"}


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


class TestDispatcherIntegration:
    """The slash dispatcher falls through to custom commands."""

    def test_unknown_verb_passes_to_custom(self, tmp_path: pathlib.Path):
        from cantrip.agent.commands import slash as slash_commands
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        commands_dir = tmp_path / ".cantrip" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "hi.md").write_text(
            "---\ndescription: greet\n---\nPlease say hi to $ARGUMENTS.\n"
        )
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        # Sanity: the agent picked up our command.
        assert "/hi" in agent.custom_commands.verbs

        result = slash_commands.dispatch(agent, "/hi world")
        assert result is not None
        assert "Running `/hi`" in result.text
        # The followup is a coroutine we can close without awaiting —
        # exercising it needs a fake provider that can handle the
        # expanded prompt.  For the dispatch path itself this is
        # sufficient.
        if result.followup is not None:
            result.followup.close()

    def test_catalogue_for_includes_custom_commands(self, tmp_path: pathlib.Path):
        from cantrip.agent.commands import slash as slash_commands
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        commands_dir = tmp_path / ".cantrip" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "triage.md").write_text(
            "---\ndescription: triage a bug\n---\nTriage ``$1``.\n"
        )
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)

        catalogue = slash_commands.catalogue_for(agent)
        verbs = {entry.verb for entry in catalogue}
        assert "/triage" in verbs
        # Built-ins still present.
        assert "/help" in verbs

    def test_help_text_lists_custom_commands(self, tmp_path: pathlib.Path):
        from cantrip.agent.commands import slash as slash_commands
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        commands_dir = tmp_path / ".cantrip" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "report.md").write_text(
            "---\ndescription: produce a report\n---\nProduce a report.\n"
        )
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)

        help_block = slash_commands.help_text(agent)
        assert "/report" in help_block
        assert "produce a report" in help_block
        assert "User commands" in help_block

    def test_help_text_without_agent_matches_builtin_only(self):
        from cantrip.agent.commands import slash as slash_commands

        text = slash_commands.help_text()
        assert "User commands" not in text


# ---------------------------------------------------------------------------
# Execution — what the dispatcher's followup coroutine actually does
# ---------------------------------------------------------------------------


def _execution_agent(
    tmp_path: pathlib.Path,
    commands: tuple[CustomCommand, ...],
    *,
    reply: str = "model reply",
) -> SimpleNamespace:
    """Smallest agent shape ``_handle_custom_command`` reads.

    Only the fall-through branch of ``dispatch`` is in play for a
    custom verb, so nothing above it in the dispatcher is touched — a
    namespace is enough, and it keeps the work-queue assertions
    readable next to a real :class:`WorkQueue`.
    """
    received: list[str] = []

    async def process_message(prompt: str) -> str:
        received.append(prompt)
        return reply

    agent = SimpleNamespace(
        custom_commands=CustomCommandRegistry(commands=commands),
        state=SimpleNamespace(charm_path=tmp_path),
        executor=None,
        process_message=process_message,
        _work_queue=queue_module.WorkQueue(),
    )
    agent._received = received
    return agent


def _command_file(tmp_path: pathlib.Path, name: str, text: str) -> CustomCommand:
    path = tmp_path / f"{name}.md"
    path.write_text(textwrap.dedent(text))
    return load_command_file(path)


class TestCustomCommandExecution:
    """The ``followup`` coroutine: expand, then route primary vs. queue."""

    async def test_primary_command_feeds_the_conversation_loop(
        self, tmp_path: pathlib.Path
    ) -> None:
        command = _command_file(
            tmp_path,
            "greet",
            """\
            ---
            description: greet
            ---
            Say hi to $ARGUMENTS.
            """,
        )
        agent = _execution_agent(tmp_path, (command,))
        result = slash_commands.dispatch(agent, "/greet the operator")
        assert result is not None
        assert result.text == "Running `/greet`…"
        assert result.followup is not None
        assert await result.followup == "model reply"
        assert agent._received == ["Say hi to the operator."]

    async def test_expansion_failure_never_reaches_the_model(self, tmp_path: pathlib.Path) -> None:
        command = _command_file(
            tmp_path,
            "readfile",
            """\
            ---
            description: read a file
            ---
            Summarise @does-not-exist.txt please.
            """,
        )
        agent = _execution_agent(tmp_path, (command,))
        result = slash_commands.dispatch(agent, "/readfile")
        assert result is not None
        assert result.followup is not None
        text = await result.followup
        assert "`/readfile` failed to expand:" in text
        assert "no such file" in text
        assert agent._received == []

    async def test_subagent_command_is_queued_not_chatted(self, tmp_path: pathlib.Path) -> None:
        command = _command_file(
            tmp_path,
            "dig",
            """\
            ---
            description: deep research
            agent: research
            ---
            Investigate $ARGUMENTS.
            """,
        )
        agent = _execution_agent(tmp_path, (command,))
        result = slash_commands.dispatch(agent, "/dig ingress")
        assert result is not None
        assert result.followup is not None
        text = await result.followup
        assert "Queued `/dig` as a research task" in text
        assert agent._received == []
        tasks = agent._work_queue.all_tasks()
        assert len(tasks) == 1
        assert tasks[0].category is queue_module.TaskCategory.RESEARCH
        assert tasks[0].description == "Investigate ingress."

    async def test_subtask_on_a_primary_command_queues_as_build(
        self, tmp_path: pathlib.Path
    ) -> None:
        """``subtask: true`` is documented as "queue it even for primary".

        ``primary`` is not a work-queue category, so the expansion
        lands under ``build`` — the neutral background category —
        rather than being rejected as an unknown agent.
        """
        command = _command_file(
            tmp_path,
            "background",
            """\
            ---
            description: run in the background
            subtask: true
            ---
            Do the slow thing.
            """,
        )
        agent = _execution_agent(tmp_path, (command,))
        result = slash_commands.dispatch(agent, "/background")
        assert result is not None
        assert result.followup is not None
        text = await result.followup
        assert "Queued `/background` as a build task" in text
        tasks = agent._work_queue.all_tasks()
        assert len(tasks) == 1
        assert tasks[0].category is queue_module.TaskCategory.BUILD

    async def test_unknown_agent_name_is_reported_not_raised(self, tmp_path: pathlib.Path) -> None:
        command = _command_file(
            tmp_path,
            "oops",
            """\
            ---
            description: typo in the agent name
            agent: reserch
            ---
            Investigate things.
            """,
        )
        agent = _execution_agent(tmp_path, (command,))
        result = slash_commands.dispatch(agent, "/oops")
        assert result is not None
        assert result.followup is not None
        text = await result.followup
        assert "names unknown agent 'reserch'" in text
        assert agent._work_queue.all_tasks() == []


class TestCustomCommandRetry:
    """``retry:`` on a primary command routes through the retry runner."""

    def _command(self, tmp_path: pathlib.Path, target: str, max_retries: int) -> CustomCommand:
        return _command_file(
            tmp_path,
            "guarded",
            f"""\
            ---
            description: write a file
            retry:
              max_retries: {max_retries}
              checks:
                - type: file_exists
                  path: {target}
            ---
            Write the file.
            """,
        )

    async def _run(self, agent: SimpleNamespace) -> str:
        result = slash_commands.dispatch(agent, "/guarded")
        assert result is not None
        assert result.followup is not None
        return await result.followup

    async def test_passing_check_returns_the_bare_reply(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "out.txt").write_text("done\n")
        agent = _execution_agent(tmp_path, (self._command(tmp_path, "out.txt", 1),))
        assert await self._run(agent) == "model reply"
        assert len(agent._received) == 1

    async def test_late_convergence_is_annotated(self, tmp_path: pathlib.Path) -> None:
        """The check fails on the first attempt and passes on the second."""
        target = tmp_path / "late.txt"
        agent = _execution_agent(tmp_path, (self._command(tmp_path, "late.txt", 2),))
        original = agent.process_message

        async def process_message(prompt: str) -> str:
            reply = await original(prompt)
            if len(agent._received) > 1:
                target.write_text("now it exists\n")
            return reply

        agent.process_message = process_message
        text = await self._run(agent)
        assert "converged after 2 attempts" in text
        assert text.startswith("model reply")

    async def test_non_convergence_lists_the_failing_checks(self, tmp_path: pathlib.Path) -> None:
        agent = _execution_agent(tmp_path, (self._command(tmp_path, "never.txt", 1),))
        text = await self._run(agent)
        assert "did not converge after 2 attempt(s)" in text
        assert "file_exists `never.txt`" in text
        assert len(agent._received) == 2
