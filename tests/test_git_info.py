"""Tests for Git metadata and worktree grouping."""

from __future__ import annotations

from pathlib import Path

from git import Repo

from iterm_agents.git_info import get_git_info
from iterm_agents.models import GitInfo


class TestGetGitInfo:
    def test_non_git_dir(self) -> None:
        info = get_git_info("/tmp")
        assert info.repo == ""
        assert info.branch == ""
        assert info.root_repo == ""

    def test_empty_path(self) -> None:
        info = get_git_info("")
        assert info == GitInfo(repo="", branch="", root_repo="")

    def test_nonexistent_path(self) -> None:
        info = get_git_info("/nonexistent/path/that/does/not/exist")
        assert info.repo == ""

    def test_normal_repo(self, tmp_path: Path) -> None:
        """A normal git repo should return repo name, branch, and root_repo == toplevel."""
        repo_dir = tmp_path / "my-project"
        repo_dir.mkdir()
        repo = Repo.init(repo_dir)
        (repo_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        repo.index.commit("init")

        info = get_git_info(str(repo_dir))
        assert info.repo == "my-project"
        assert info.branch in ("master", "main")
        assert info.root_repo == str(repo_dir)

    def test_worktree_uses_main_repo_name(self, tmp_path: Path) -> None:
        """A worktree should report the main repo's name, not the worktree dir name."""
        main_dir = tmp_path / "my-project"
        main_dir.mkdir()
        repo = Repo.init(main_dir)
        (main_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        repo.index.commit("init")

        repo.git.branch("feature-branch")
        wt_dir = tmp_path / "20260401_worktree_feature"
        repo.git.worktree("add", str(wt_dir), "feature-branch")

        info = get_git_info(str(wt_dir))
        assert info.repo == "my-project"
        assert info.branch == "feature-branch"
        assert info.root_repo == str(main_dir)

    def test_subdirectory_of_repo(self, tmp_path: Path) -> None:
        """get_git_info from a subdirectory should still find the repo."""
        repo_dir = tmp_path / "my-project"
        sub_dir = repo_dir / "src" / "app"
        sub_dir.mkdir(parents=True)
        repo = Repo.init(repo_dir)
        (repo_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        repo.index.commit("init")

        info = get_git_info(str(sub_dir))
        assert info.repo == "my-project"

    def test_detached_head(self, tmp_path: Path) -> None:
        """Detached HEAD should return empty branch."""
        repo_dir = tmp_path / "my-project"
        repo_dir.mkdir()
        repo = Repo.init(repo_dir)
        (repo_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        commit = repo.index.commit("init")

        repo.head.reference = commit  # type: ignore[assignment]
        repo.head.reset(index=True, working_tree=True)

        info = get_git_info(str(repo_dir))
        assert info.repo == "my-project"
        assert info.branch == ""
