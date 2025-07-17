"""Repository management utilities for cloning and managing GitHub repositories."""

import os
import tempfile
import shutil
import re
from typing import Optional, Tuple
import git
from utils.logging import get_logger

logger = get_logger(__name__)


class RepositoryManager:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.cloned_repos = {}  # Track cloned repositories for cleanup

    def parse_github_url(self, repo_url: str) -> Tuple[str, str]:
        # Extract owner/repo from any GitHub URL format
        pattern = r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git|/|$)"
        match = re.search(pattern, repo_url)

        if not match:
            raise ValueError(f"Invalid GitHub URL format: {repo_url}")

        owner, repo_name = match.groups()
        if not owner or not repo_name:
            raise ValueError(f"Could not extract owner/repo from URL: {repo_url}")

        return owner, repo_name

    def get_clone_path(self, repo_url: str) -> str:
        owner, repo_name = self.parse_github_url(repo_url)
        return os.path.join(self.base_dir, "codemind-repos", f"{owner}_{repo_name}")

    def clone_repository(
        self,
        repo_url: str,
        branch: str = "main",
        access_token: Optional[str] = None,
        force_refresh: bool = False,
    ) -> str:
        try:
            owner, repo_name = self.parse_github_url(repo_url)
            clone_path = self.get_clone_path(repo_url)

            # Check if already cloned
            if os.path.exists(clone_path) and not force_refresh:
                logger.info(f"Repository already cloned at: {clone_path}")
                # Try to pull latest changes
                try:
                    repo = git.Repo(clone_path)
                    repo.remotes.origin.pull()
                    logger.info(f"Updated repository: {owner}/{repo_name}")
                except Exception as e:
                    logger.warning(f"Failed to update repository: {e}")
                return clone_path

            # Remove existing directory if force refresh
            if os.path.exists(clone_path) and force_refresh:
                shutil.rmtree(clone_path)
                logger.info(f"Removed existing clone: {clone_path}")

            # Prepare clone URL with token if provided
            if access_token:
                clone_url = f"https://{access_token}@github.com/{owner}/{repo_name}.git"
            else:
                clone_url = f"https://github.com/{owner}/{repo_name}.git"

            # Create parent directory
            os.makedirs(os.path.dirname(clone_path), exist_ok=True)

            # Clone repository
            logger.info(
                f"Cloning {owner}/{repo_name} (branch: {branch}) to {clone_path}"
            )
            try:
                repo = git.Repo.clone_from(
                    clone_url,
                    clone_path,
                    branch=branch,
                    depth=1,  # Shallow clone for faster cloning
                )
            except git.exc.GitCommandError as e:
                if "Remote branch" in str(e) and "not found" in str(e):
                    # Try to clone without specifying branch (uses default)
                    logger.info(f"Branch '{branch}' not found, trying default branch")
                    repo = git.Repo.clone_from(
                        clone_url,
                        clone_path,
                        depth=1,  # Shallow clone for faster cloning
                    )
                else:
                    raise

            # Track cloned repository
            self.cloned_repos[repo_url] = clone_path

            logger.info(f"Successfully cloned repository: {owner}/{repo_name}")
            return clone_path

        except git.exc.GitCommandError as e:
            if "Repository not found" in str(e):
                raise Exception(f"Repository not found or access denied: {repo_url}")
            elif "Invalid username or password" in str(e):
                raise Exception(
                    f"Invalid access token or repository is private: {repo_url}"
                )
            else:
                raise Exception(f"Git error while cloning {repo_url}: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to clone repository {repo_url}: {str(e)}")

    def cleanup_repository(self, repo_url: str) -> bool:
        try:
            if repo_url in self.cloned_repos:
                clone_path = self.cloned_repos[repo_url]
                if os.path.exists(clone_path):
                    shutil.rmtree(clone_path)
                    logger.info(f"Cleaned up repository: {clone_path}")
                del self.cloned_repos[repo_url]
                return True
        except Exception as e:
            logger.error(f"Failed to cleanup repository {repo_url}: {e}")
            return False
        return True

    def cleanup_all(self):
        for repo_url in list(self.cloned_repos.keys()):
            self.cleanup_repository(repo_url)

    def get_repository_info(self, repo_url: str) -> dict:
        try:
            owner, repo_name = self.parse_github_url(repo_url)
            return {
                "owner": owner,
                "repo_name": repo_name,
                "full_name": f"{owner}/{repo_name}",
                "clone_url": repo_url,
                "local_path": self.get_clone_path(repo_url),
            }
        except Exception as e:
            raise Exception(f"Failed to parse repository URL: {str(e)}")


# Global repository manager instance
_repo_manager = RepositoryManager()


def get_repo_manager() -> RepositoryManager:
    return _repo_manager
