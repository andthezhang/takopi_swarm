from pathlib import Path
from types import SimpleNamespace

import pytest

from takopi.config import ProjectConfig, ProjectsConfig
from takopi.context import RunContext
from takopi.worktrees import WorktreeError, ensure_worktree, resolve_run_cwd


def _projects_config(path: Path) -> ProjectsConfig:
    return ProjectsConfig(
        projects={
            "z80": ProjectConfig(
                alias="z80",
                path=path,
                worktrees_dir=Path(".worktrees"),
            )
        },
        default_project=None,
    )


def test_resolve_run_cwd_uses_project_root(tmp_path: Path) -> None:
    projects = _projects_config(tmp_path)
    ctx = RunContext(project="z80")
    assert resolve_run_cwd(ctx, projects=projects) == tmp_path


def test_resolve_run_cwd_rejects_invalid_branch(tmp_path: Path) -> None:
    projects = _projects_config(tmp_path)
    ctx = RunContext(project="z80", branch="../oops")
    with pytest.raises(WorktreeError, match="branch name"):
        resolve_run_cwd(ctx, projects=projects)


def test_resolve_run_cwd_uses_root_when_branch_is_base(
    monkeypatch, tmp_path: Path
) -> None:
    projects = _projects_config(tmp_path)

    def _fake_stdout(args, **_kwargs):
        if args == ["branch", "--show-current"]:
            return "main"
        return None

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("unexpected")

    monkeypatch.setattr("takopi.worktrees.git_stdout", _fake_stdout)
    monkeypatch.setattr("takopi.worktrees.resolve_default_base", lambda _root: "main")
    monkeypatch.setattr(
        "takopi.worktrees.ensure_worktree",
        _unexpected,
    )

    ctx = RunContext(project="z80", branch="main")
    assert resolve_run_cwd(ctx, projects=projects) == tmp_path


def test_resolve_run_cwd_non_base_branch_uses_worktree_even_if_root_matches(
    monkeypatch, tmp_path: Path
) -> None:
    projects = ProjectsConfig(
        projects={
            "z80": ProjectConfig(
                alias="z80",
                path=tmp_path,
                worktrees_dir=Path(".worktrees"),
                worktree_base="main",
            )
        },
        default_project=None,
    )

    def _fake_stdout(args, **_kwargs):
        if args == ["branch", "--show-current"]:
            return "feature-x"
        return None

    captured: list[str] = []
    expected = tmp_path / ".worktrees" / "feature-x"

    def _fake_ensure(_project, branch):
        captured.append(branch)
        return expected

    monkeypatch.setattr("takopi.worktrees.git_stdout", _fake_stdout)
    monkeypatch.setattr("takopi.worktrees.ensure_worktree", _fake_ensure)

    ctx = RunContext(project="z80", branch="feature-x")
    assert resolve_run_cwd(ctx, projects=projects) == expected
    assert captured == ["feature-x"]


def test_resolve_run_cwd_base_branch_requires_root_checkout(
    monkeypatch, tmp_path: Path
) -> None:
    projects = ProjectsConfig(
        projects={
            "z80": ProjectConfig(
                alias="z80",
                path=tmp_path,
                worktrees_dir=Path(".worktrees"),
                worktree_base="main",
            )
        },
        default_project=None,
    )

    def _fake_stdout(args, **_kwargs):
        if args == ["branch", "--show-current"]:
            return "feature-x"
        return None

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("unexpected")

    monkeypatch.setattr("takopi.worktrees.git_stdout", _fake_stdout)
    monkeypatch.setattr("takopi.worktrees.ensure_worktree", _unexpected)

    ctx = RunContext(project="z80", branch="main")
    with pytest.raises(WorktreeError, match="mainline branches"):
        resolve_run_cwd(ctx, projects=projects)


def test_resolve_run_cwd_base_branch_uses_project_root(
    monkeypatch, tmp_path: Path
) -> None:
    projects = ProjectsConfig(
        projects={
            "z80": ProjectConfig(
                alias="z80",
                path=tmp_path,
                worktrees_dir=Path(".worktrees"),
                worktree_base="main",
            )
        },
        default_project=None,
    )

    def _fake_stdout(args, **_kwargs):
        if args == ["branch", "--show-current"]:
            return "main"
        return None

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("unexpected")

    monkeypatch.setattr("takopi.worktrees.git_stdout", _fake_stdout)
    monkeypatch.setattr("takopi.worktrees.ensure_worktree", _unexpected)

    ctx = RunContext(project="z80", branch="main")
    assert resolve_run_cwd(ctx, projects=projects) == tmp_path


@pytest.mark.parametrize(
    ("requested_branch", "current_branch"),
    [("main", "master"), ("master", "main")],
)
def test_resolve_run_cwd_main_master_alias_uses_project_root(
    monkeypatch,
    tmp_path: Path,
    requested_branch: str,
    current_branch: str,
) -> None:
    projects = ProjectsConfig(
        projects={
            "z80": ProjectConfig(
                alias="z80",
                path=tmp_path,
                worktrees_dir=Path(".worktrees"),
                worktree_base="main",
            )
        },
        default_project=None,
    )

    def _fake_stdout(args, **_kwargs):
        if args == ["branch", "--show-current"]:
            return current_branch
        return None

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("unexpected")

    monkeypatch.setattr("takopi.worktrees.git_stdout", _fake_stdout)
    monkeypatch.setattr("takopi.worktrees.ensure_worktree", _unexpected)

    ctx = RunContext(project="z80", branch=requested_branch)
    assert resolve_run_cwd(ctx, projects=projects) == tmp_path


def test_ensure_worktree_creates_from_base(monkeypatch, tmp_path: Path) -> None:
    project = ProjectConfig(
        alias="z80",
        path=tmp_path,
        worktrees_dir=Path(".worktrees"),
    )
    calls: list[list[str]] = []

    monkeypatch.setattr("takopi.worktrees.git_ok", lambda *args, **kwargs: False)
    monkeypatch.setattr("takopi.worktrees.resolve_default_base", lambda *_: "main")

    def _fake_git_run(args, cwd):
        calls.append(list(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("takopi.worktrees.git_run", _fake_git_run)

    worktree_path = ensure_worktree(project, "feat/name")
    assert worktree_path == tmp_path / ".worktrees" / "feat" / "name"
    assert calls == [["worktree", "add", "-b", "feat/name", str(worktree_path), "main"]]


def test_ensure_worktree_rejects_existing_non_worktree(
    monkeypatch, tmp_path: Path
) -> None:
    project = ProjectConfig(
        alias="z80",
        path=tmp_path,
        worktrees_dir=Path(".worktrees"),
    )
    worktree_path = tmp_path / ".worktrees" / "foo"
    worktree_path.mkdir(parents=True)

    def _fake_stdout(args, **kwargs):
        if args == ["rev-parse", "--is-inside-work-tree"]:
            return "true"
        if args == ["rev-parse", "--path-format=absolute", "--show-toplevel"]:
            return str(tmp_path)
        return None

    monkeypatch.setattr("takopi.utils.git.git_stdout", _fake_stdout)

    with pytest.raises(WorktreeError, match="exists but is not a git worktree"):
        ensure_worktree(project, "foo")
