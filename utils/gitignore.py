"""
.gitignore file parsing and pattern matching utilities.
"""

import re
from pathlib import Path
from typing import List, Optional
from utils.logging import get_logger

logger = get_logger(__name__)


# Default gitignore patterns for common files that should typically be ignored
DEFAULT_GITIGNORE_PATTERNS = [
    # Version control
    ".git/",
    ".svn/",
    ".hg/",
    
    # Build artifacts
    "build/",
    "dist/",
    "target/",
    "out/",
    "*.o",
    "*.obj",
    "*.exe",
    "*.dll",
    "*.so",
    "*.dylib",
    
    # Dependencies
    "node_modules/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/",
    "vendor/",
    "Pods/",
    
    # IDE files
    ".vscode/",
    ".idea/",
    "*.swp",
    "*.swo",
    "*~",
    ".DS_Store",
    "Thumbs.db",
    
    # Logs
    "*.log",
    "logs/",
    
    # Environment files
    ".env",
    ".env.local",
    ".env.*.local",
    
    # Package files
    "*.zip",
    "*.tar.gz",
    "*.rar",
    "*.7z",
    
    # Media files
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.gif",
    "*.bmp",
    "*.ico",
    "*.mp3",
    "*.mp4",
    "*.avi",
    "*.mov",
    "*.wav",
    
    # Documents
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.xls",
    "*.xlsx",
    "*.ppt",
    "*.pptx",
]


class GitignoreParser:
    """Parser for .gitignore files with pattern matching."""

    def __init__(self, repo_path: str, use_default_patterns: bool = False):
        self.repo_path = Path(repo_path)
        self.patterns: List[GitignorePattern] = []
        self.use_default_patterns = use_default_patterns
        self._load_gitignore_files()

    def _load_gitignore_files(self):
        """Load all .gitignore files in the repository."""
        gitignore_files_found = False
        
        # Load global .gitignore from repo root
        global_gitignore = self.repo_path / ".gitignore"
        if global_gitignore.exists():
            self._parse_gitignore_file(global_gitignore, self.repo_path)
            gitignore_files_found = True

        # Load .gitignore files from subdirectories
        for gitignore_file in self.repo_path.rglob(".gitignore"):
            if gitignore_file != global_gitignore:
                gitignore_dir = gitignore_file.parent
                self._parse_gitignore_file(gitignore_file, gitignore_dir)
                gitignore_files_found = True
        
        # If no .gitignore files found and default patterns requested, add them
        if not gitignore_files_found and self.use_default_patterns:
            logger.debug("No .gitignore files found, using default patterns")
            self.patterns.extend(create_default_gitignore_patterns())

    def _parse_gitignore_file(self, gitignore_path: Path, base_dir: Path):
        """Parse a single .gitignore file."""
        try:
            content = gitignore_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            for line_num, line in enumerate(lines, 1):
                pattern = self._parse_line(line, base_dir, gitignore_path, line_num)
                if pattern:
                    self.patterns.append(pattern)

        except Exception as e:
            logger.warning(f"Error reading .gitignore file {gitignore_path}: {e}")

    def _parse_line(
        self, line: str, base_dir: Path, gitignore_path: Path, line_num: int
    ) -> Optional["GitignorePattern"]:
        """Parse a single line from .gitignore file."""
        # Remove comments and whitespace
        line = line.strip()
        if not line or line.startswith("#"):
            return None

        # Handle negation
        negate = False
        if line.startswith("!"):
            negate = True
            line = line[1:]

        if not line:
            return None

        return GitignorePattern(
            pattern=line,
            base_dir=base_dir,
            negate=negate,
            source_file=gitignore_path,
            line_number=line_num,
        )

    def should_ignore(self, file_path: Path) -> bool:
        """Check if a file should be ignored based on .gitignore patterns."""
        # Check if file is within the repository
        try:
            file_path.relative_to(self.repo_path)
        except ValueError:
            # File is outside repo, don't ignore
            return False

        # Check patterns in order (later patterns can override earlier ones)
        ignored = False

        for pattern in self.patterns:
            if pattern.matches(file_path, self.repo_path):
                ignored = not pattern.negate  # If negate=True, then don't ignore

        return ignored

    def get_patterns(self) -> List["GitignorePattern"]:
        """Get all loaded patterns."""
        return self.patterns.copy()


class GitignorePattern:
    """Represents a single .gitignore pattern."""

    def __init__(
        self,
        pattern: str,
        base_dir: Path,
        negate: bool = False,
        source_file: Optional[Path] = None,
        line_number: Optional[int] = None,
    ):
        self.original_pattern = pattern
        self.base_dir = base_dir
        self.negate = negate
        self.source_file = source_file
        self.line_number = line_number

        # Process the pattern
        self.is_directory_only = pattern.endswith("/")
        if self.is_directory_only:
            pattern = pattern[:-1]

        self.is_absolute = pattern.startswith("/")
        if self.is_absolute:
            pattern = pattern[1:]

        self.pattern = pattern
        self.has_slash = "/" in pattern

        # Convert gitignore pattern to regex
        self.regex = self._pattern_to_regex(pattern)

    def _pattern_to_regex(self, pattern: str) -> re.Pattern:
        """Convert gitignore pattern to regex."""
        # Handle ** first (before escaping)
        pattern = pattern.replace("**", "__DOUBLESTAR__")

        # Escape special regex characters except * and ?
        escaped = re.escape(pattern)

        # Convert gitignore wildcards to regex
        escaped = escaped.replace(
            "__DOUBLESTAR__", ".*"
        )  # ** matches any number of directories
        escaped = escaped.replace(r"\*", "[^/]*")  # * matches anything except /
        escaped = escaped.replace(r"\?", "[^/]")  # ? matches single character except /

        # Handle directory separators - don't escape them
        escaped = escaped.replace(r"\/", "/")

        return re.compile(escaped + "$")

    def matches(self, file_path: Path, repo_root: Path) -> bool:
        """Check if this pattern matches the given file path."""
        # Convert to relative path from repo root
        try:
            rel_path = file_path.relative_to(repo_root)
        except ValueError:
            return False

        # Convert to string with forward slashes
        path_str = str(rel_path).replace("\\", "/")

        # If pattern is directory-only, only match directories
        if self.is_directory_only:
            if not file_path.is_dir():
                # For directory patterns, also check if any parent directory matches
                parent_path = file_path.parent
                while parent_path != repo_root:
                    try:
                        parent_rel = parent_path.relative_to(repo_root)
                        parent_str = str(parent_rel).replace("\\", "/")
                        if self.regex.match(parent_str):
                            return True
                    except ValueError:
                        break
                    parent_path = parent_path.parent
                return False

        # Handle absolute patterns (start from repo root)
        if self.is_absolute:
            return bool(self.regex.match(path_str))

        # Handle patterns with slashes (must match from specific directory level)
        if self.has_slash:
            # Try to match the full path
            if self.regex.match(path_str):
                return True
            # Also try matching from any directory level
            parts = path_str.split("/")
            for i in range(len(parts)):
                subpath = "/".join(parts[i:])
                if self.regex.match(subpath):
                    return True
            return False

        # Pattern without slashes - match against filename or any directory level
        filename = file_path.name
        if self.regex.match(filename):
            return True

        # Also try matching against each directory level
        parts = path_str.split("/")
        for i in range(len(parts)):
            subpath = "/".join(parts[i:])
            if self.regex.match(subpath):
                return True

        return False

    def __str__(self) -> str:
        prefix = "!" if self.negate else ""
        suffix = "/" if self.is_directory_only else ""
        abs_prefix = "/" if self.is_absolute else ""
        return f"{prefix}{abs_prefix}{self.pattern}{suffix}"

    def __repr__(self) -> str:
        return f"GitignorePattern('{self}', base_dir='{self.base_dir}')"


def create_default_gitignore_patterns() -> List[GitignorePattern]:
    """Create default patterns for common files to ignore."""
    patterns = []
    for pattern_str in DEFAULT_GITIGNORE_PATTERNS:
        pattern = GitignorePattern(
            pattern=pattern_str, base_dir=Path("."), negate=False
        )
        patterns.append(pattern)

    return patterns


def get_default_gitignore_patterns() -> List[str]:
    """Get the list of default gitignore pattern strings."""
    return DEFAULT_GITIGNORE_PATTERNS.copy()


def should_ignore_by_default_patterns(file_path: str) -> bool:
    """Check if a file should be ignored based on default patterns only."""
    temp_patterns = create_default_gitignore_patterns()
    file_path_obj = Path(file_path)
    
    for pattern in temp_patterns:
        if pattern.matches(file_path_obj, Path(".")):
            return True
    
    return False
