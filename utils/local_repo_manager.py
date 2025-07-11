"""Local Git repository management utilities for native local codebase support."""

from pathlib import Path
from typing import Optional, Dict, Any
import git
from urllib.parse import urlparse
from utils.logging import get_logger

logger = get_logger(__name__)


class LocalRepositoryManager:
    """Manages local Git repositories as first-class citizens."""

    def __init__(self):
        pass

    def is_git_repository(self, path: str) -> bool:
        """Check if the given path is a Git repository."""
        try:
            git.Repo(path, search_parent_directories=True)
            return True
        except (git.exc.InvalidGitRepositoryError, git.exc.GitCommandError):
            return False

    def get_repository_info(self, path: str) -> Dict[str, Any]:
        """Extract comprehensive repository information from a local Git repository."""
        path = Path(path).resolve()

        if not self.is_git_repository(str(path)):
            # For non-Git directories, create a synthetic repository info
            return self._create_synthetic_repo_info(path)

        try:
            repo = git.Repo(path, search_parent_directories=True)
            repo_root = Path(repo.working_dir)

            # Get current branch
            try:
                current_branch = repo.active_branch.name
            except TypeError:
                # Detached HEAD state
                current_branch = "HEAD"

            # Get remote information
            remote_url = None
            remote_name = None
            origin_owner = None
            origin_repo_name = None

            if repo.remotes:
                origin = (
                    repo.remotes.origin
                    if "origin" in [r.name for r in repo.remotes]
                    else repo.remotes[0]
                )
                remote_url = list(origin.urls)[0] if origin.urls else None
                remote_name = origin.name

                # Parse remote URL for GitHub info
                if remote_url:
                    origin_owner, origin_repo_name = self._parse_remote_url(remote_url)

            # Get commit information
            try:
                latest_commit = repo.head.commit
                latest_commit_hash = latest_commit.hexsha[:8]
                latest_commit_message = latest_commit.message.strip()
                latest_commit_author = str(latest_commit.author)
                latest_commit_date = latest_commit.committed_datetime.isoformat()
            except Exception:
                latest_commit_hash = "unknown"
                latest_commit_message = "No commits"
                latest_commit_author = "unknown"
                latest_commit_date = "unknown"

            # Create repository identifier
            repo_id = self._generate_local_repo_id(repo_root, remote_url)

            # Create repository URL
            if remote_url:
                repo_url = remote_url
            else:
                repo_url = f"file://{repo_root}"

            return {
                "repo_id": repo_id,
                "repo_url": repo_url,
                "repo_name": origin_repo_name or repo_root.name,
                "owner": origin_owner or "local",
                "branch": current_branch,
                "local_path": str(repo_root),
                "is_local": True,
                "has_remote": remote_url is not None,
                "remote_url": remote_url,
                "remote_name": remote_name,
                "latest_commit": {
                    "hash": latest_commit_hash,
                    "message": latest_commit_message,
                    "author": latest_commit_author,
                    "date": latest_commit_date,
                },
                "repository_type": "git",
            }

        except Exception as e:
            logger.error(f"Error extracting Git repository info from {path}: {e}")
            return self._create_synthetic_repo_info(path)

    def _create_synthetic_repo_info(self, path: Path) -> Dict[str, Any]:
        """Create repository info for non-Git directories."""
        repo_id = self._generate_local_repo_id(path, None)

        return {
            "repo_id": repo_id,
            "repo_url": f"file://{path}",
            "repo_name": path.name,
            "owner": "local",
            "branch": "main",
            "local_path": str(path),
            "is_local": True,
            "has_remote": False,
            "remote_url": None,
            "remote_name": None,
            "latest_commit": {
                "hash": "no-git",
                "message": "Not a Git repository",
                "author": "local",
                "date": "unknown",
            },
            "repository_type": "directory",
        }

    def _generate_local_repo_id(
        self, repo_path: Path, remote_url: Optional[str]
    ) -> str:
        """Generate a unique identifier for a local repository."""
        if remote_url:
            # Use remote URL for consistent ID across clones
            import hashlib

            return hashlib.md5(remote_url.encode()).hexdigest()[:12]
        else:
            # Use absolute path for local-only repositories
            import hashlib

            return hashlib.md5(str(repo_path).encode()).hexdigest()[:12]

    def _parse_remote_url(self, remote_url: str) -> tuple[Optional[str], Optional[str]]:
        """Parse remote URL to extract owner and repository name."""
        try:
            # Handle different URL formats
            if remote_url.startswith("git@"):
                # SSH format: git@github.com:owner/repo.git
                parts = remote_url.replace("git@", "").replace(".git", "").split(":")
                if len(parts) == 2:
                    host_part, repo_part = parts
                    if "/" in repo_part:
                        owner, repo_name = repo_part.split("/", 1)
                        return owner, repo_name
            else:
                # HTTPS format: https://github.com/owner/repo.git
                parsed = urlparse(remote_url)
                if parsed.path:
                    path_parts = parsed.path.strip("/").replace(".git", "").split("/")
                    if len(path_parts) >= 2:
                        return path_parts[0], path_parts[1]
        except Exception as e:
            logger.debug(f"Could not parse remote URL {remote_url}: {e}")

        return None, None

    def get_repository_status(self, path: str) -> Dict[str, Any]:
        """Get the current status of a Git repository."""
        if not self.is_git_repository(path):
            return {"is_git": False, "status": "not_a_git_repository"}

        try:
            repo = git.Repo(path, search_parent_directories=True)

            # Check for uncommitted changes
            is_dirty = repo.is_dirty(untracked_files=True)
            untracked_files = repo.untracked_files
            modified_files = [item.a_path for item in repo.index.diff(None)]
            staged_files = [item.a_path for item in repo.index.diff("HEAD")]

            return {
                "is_git": True,
                "is_dirty": is_dirty,
                "untracked_files": untracked_files,
                "modified_files": modified_files,
                "staged_files": staged_files,
                "status": "clean" if not is_dirty else "dirty",
            }

        except Exception as e:
            logger.error(f"Error getting repository status for {path}: {e}")
            return {"is_git": True, "status": "error", "error": str(e)}


# Global local repository manager instance
_local_repo_manager = LocalRepositoryManager()


def get_local_repo_manager() -> LocalRepositoryManager:
    """Get the global local repository manager instance."""
    return _local_repo_manager


def is_github_url(url: str) -> bool:
    """Check if a URL is a GitHub URL."""
    return "github.com" in url.lower()


def is_local_path(path: str) -> bool:
    """Check if a path is a local file system path."""
    return not (
        path.startswith("http://")
        or path.startswith("https://")
        or path.startswith("git@")
    )
