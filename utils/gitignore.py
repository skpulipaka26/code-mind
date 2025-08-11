"""
Reliable gitignore handling using the pathspec library.
"""

import pathspec
from pathlib import Path
from typing import List
from utils.logging import get_logger

logger = get_logger(__name__)


class GitignoreParser:
    """Gitignore parser using pathspec library."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self.spec = self._load_gitignore_spec()

    def _load_gitignore_spec(self) -> pathspec.PathSpec:
        """Load gitignore patterns from .gitignore files."""
        patterns = []

        # Load root .gitignore
        root_gitignore = self.repo_path / ".gitignore"
        if root_gitignore.exists():
            try:
                with open(root_gitignore, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
                    # Filter out empty lines and comments
                    filtered_lines = [
                        line
                        for line in lines
                        if line.strip() and not line.strip().startswith("#")
                    ]
                    patterns.extend(filtered_lines)
                logger.debug(f"Loaded {len(patterns)} patterns from {root_gitignore}")
            except Exception as e:
                logger.warning(f"Error reading {root_gitignore}: {e}")

        # Add some essential default patterns if no .gitignore exists
        if not patterns:
            patterns = [
                ".git/",
                "__pycache__/",
                "*.pyc",
                "*.pyo",
                ".pytest_cache/",
                "node_modules/",
                ".venv/",
                ".env",
                "build/",
                "dist/",
            ]
            logger.debug("No .gitignore found, using default patterns")

        # Create pathspec from patterns
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def should_ignore(self, file_path: Path) -> bool:
        """Check if a file should be ignored."""
        try:
            # Ensure we have an absolute path
            abs_path = file_path.resolve() if not file_path.is_absolute() else file_path

            # Get relative path from repo root
            rel_path = abs_path.relative_to(self.repo_path)

            # Convert to string with forward slashes (pathspec expects this)
            path_str = str(rel_path).replace("\\", "/")

            # Check if path matches any ignore pattern
            return self.spec.match_file(path_str)

        except ValueError:
            # File is outside repo, don't ignore
            return False
        except Exception as e:
            logger.debug(f"Error checking ignore status for {file_path}: {e}")
            return False

    def get_patterns(self) -> List[str]:
        """Get the loaded patterns (for debugging)."""
        # Extract pattern strings from pathspec objects
        return [str(pattern.pattern) for pattern in self.spec.patterns]


def test_gitignore_parser():
    """Test the gitignore parser."""
    parser = GitignoreParser(".")

    test_files = [
        "config.py",
        "core/chunker.py",
        "__pycache__/test.pyc",
        ".venv/lib/python3.12/site-packages/click/__init__.py",
        ".git/config",
        "build/output.txt",
        "dist/package.tar.gz",
    ]

    print(f"Loaded {len(parser.get_patterns())} gitignore patterns")
    print("\nTesting files:")
    for file_path in test_files:
        path = Path(file_path)
        ignored = parser.should_ignore(path)
        exists = "✓" if path.exists() else "✗"
        print(f"  {file_path:<50} ignored={ignored:<5} exists={exists}")


if __name__ == "__main__":
    test_gitignore_parser()
