"""
Repository management utilities for cloning and managing GitHub repositories.
"""

import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
import git
from utils.logging import get_logger

logger = get_logger(__name__)


class RepositoryManager:
    """Manages repository cloning and cleanup."""
    
    def __init__(self, base_dir: Optional[str] = None):
        """Initialize repository manager.
        
        Args:
            base_dir: Base directory for cloning repos. If None, uses temp directory.
        """
        self.base_dir = base_dir or tempfile.gettempdir()
        self.cloned_repos = {}  # Track cloned repositories for cleanup
    
    def parse_github_url(self, repo_url: str) -> Tuple[str, str]:
        """Parse GitHub URL to extract owner and repo name.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            Tuple of (owner, repo_name)
            
        Raises:
            ValueError: If URL is not a valid GitHub URL
        """
        # Handle different GitHub URL formats
        if repo_url.startswith("git@github.com:"):
            # SSH format: git@github.com:owner/repo.git
            path = repo_url.replace("git@github.com:", "").replace(".git", "")
        elif "github.com" in repo_url:
            # HTTPS format: https://github.com/owner/repo or https://github.com/owner/repo.git
            parsed = urlparse(repo_url)
            if parsed.netloc != "github.com":
                raise ValueError(f"Only GitHub repositories are supported, got: {parsed.netloc}")
            path = parsed.path.strip("/").replace(".git", "")
        else:
            raise ValueError(f"Invalid GitHub URL format: {repo_url}")
        
        parts = path.split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid GitHub repository path: {path}")
        
        return parts[0], parts[1]
    
    def get_clone_path(self, repo_url: str) -> str:
        """Get the local path where repository should be cloned.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            Local path for the repository
        """
        owner, repo_name = self.parse_github_url(repo_url)
        return os.path.join(self.base_dir, "codemind-repos", f"{owner}_{repo_name}")
    
    def clone_repository(
        self, 
        repo_url: str, 
        branch: str = "main",
        access_token: Optional[str] = None,
        force_refresh: bool = False
    ) -> str:
        """Clone a GitHub repository.
        
        Args:
            repo_url: GitHub repository URL
            branch: Branch to clone (default: main)
            access_token: GitHub access token for private repos
            force_refresh: If True, delete existing clone and re-clone
            
        Returns:
            Local path to the cloned repository
            
        Raises:
            Exception: If cloning fails
        """
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
            logger.info(f"Cloning {owner}/{repo_name} (branch: {branch}) to {clone_path}")
            repo = git.Repo.clone_from(
                clone_url,
                clone_path,
                branch=branch,
                depth=1  # Shallow clone for faster cloning
            )
            
            # Track cloned repository
            self.cloned_repos[repo_url] = clone_path
            
            logger.info(f"Successfully cloned repository: {owner}/{repo_name}")
            return clone_path
            
        except git.exc.GitCommandError as e:
            if "Repository not found" in str(e):
                raise Exception(f"Repository not found or access denied: {repo_url}")
            elif "Invalid username or password" in str(e):
                raise Exception(f"Invalid access token or repository is private: {repo_url}")
            else:
                raise Exception(f"Git error while cloning {repo_url}: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to clone repository {repo_url}: {str(e)}")
    
    def cleanup_repository(self, repo_url: str) -> bool:
        """Clean up a cloned repository.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            True if cleanup was successful
        """
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
        """Clean up all cloned repositories."""
        for repo_url in list(self.cloned_repos.keys()):
            self.cleanup_repository(repo_url)
    
    def get_repository_info(self, repo_url: str) -> dict:
        """Get information about a repository without cloning.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            Dictionary with repository information
        """
        try:
            owner, repo_name = self.parse_github_url(repo_url)
            return {
                "owner": owner,
                "repo_name": repo_name,
                "full_name": f"{owner}/{repo_name}",
                "clone_url": repo_url,
                "local_path": self.get_clone_path(repo_url)
            }
        except Exception as e:
            raise Exception(f"Failed to parse repository URL: {str(e)}")


# Global repository manager instance
_repo_manager = RepositoryManager()


def get_repo_manager() -> RepositoryManager:
    """Get the global repository manager instance."""
    return _repo_manager