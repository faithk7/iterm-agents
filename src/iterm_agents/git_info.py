"""Best-effort Git metadata and worktree grouping for session directories."""

from __future__ import annotations

import os
from pathlib import Path

from git import Repo

from iterm_agents.models import GitInfo


def get_git_info(path: str) -> GitInfo:
    """Get git repo name, branch, and root repo path for a directory.

    For worktrees, root_repo points to the main repository's toplevel,
    so sessions in different worktrees of the same repo get grouped together.
    """
    empty = GitInfo(repo="", branch="", root_repo="")
    if not path or not os.path.isdir(path):
        return empty
    try:
        repo = Repo(path, search_parent_directories=True)
    except Exception:
        return empty

    try:
        toplevel = str(repo.working_tree_dir or "")
        repo_name = os.path.basename(toplevel) if toplevel else ""

        branch = ""
        if not repo.head.is_detached:
            branch = repo.active_branch.name

        # Resolve root repo for worktree grouping.
        # repo.common_dir points to the shared .git dir (same for all worktrees).
        # For normal repos: /path/to/repo/.git
        # For worktrees: /path/to/main-repo/.git (the main repo's git dir)
        root_repo = toplevel
        common_dir = Path(repo.common_dir).resolve()
        if common_dir != Path(repo.git_dir).resolve():
            # This is a worktree; common_dir is the main repo's .git
            root_repo = str(common_dir.parent)
            # Use the main repo's name, not the worktree directory name
            repo_name = os.path.basename(root_repo)

        return GitInfo(repo=repo_name, branch=branch, root_repo=root_repo)
    except Exception:
        return empty
