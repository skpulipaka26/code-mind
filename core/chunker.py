from typing import List
from pathlib import Path

from core.generic_extractor import GenericChunkExtractor
from core.chunk_types import CodeChunk
from core.language_registry import get_language_registry
from utils.gitignore import GitignoreParser, should_ignore_by_default_patterns
from utils.logging import get_logger

logger = get_logger(__name__)


class TreeSitterChunker:
    """Extract code chunks using Tree-sitter with dynamic language support."""

    def __init__(self):
        self.extractor = GenericChunkExtractor()
        self.registry = get_language_registry()
        self.gitignore_parser = None

    def chunk_file(self, file_path: str, content: str) -> List[CodeChunk]:
        """Extract chunks from a file."""
        return self.extractor.extract_chunks(file_path, content)

    def chunk_repository(self, repo_path: str) -> List[CodeChunk]:
        """Extract chunks from repository."""
        chunks = []
        repo_path = Path(repo_path)

        # Initialize gitignore parser for this repository
        # Use default patterns as fallback when no .gitignore exists
        self.gitignore_parser = GitignoreParser(str(repo_path), use_default_patterns=True)
        logger.debug(
            f"Loaded {len(self.gitignore_parser.get_patterns())} .gitignore patterns"
        )

        # Process all files, not just Tree-sitter supported ones
        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue

            # Check .gitignore patterns first
            if self.gitignore_parser.should_ignore(file_path):
                logger.debug(f"Skipping file due to .gitignore: {file_path}")
                continue

            # Check other skip conditions
            if self._should_skip(file_path):
                continue

            # Check if file is supported (includes fallback support)
            if not self.extractor.is_supported_file(str(file_path)):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                file_chunks = self.chunk_file(str(file_path), content)
                chunks.extend(file_chunks)
            except UnicodeDecodeError:
                logger.debug(f"Skipping binary file: {file_path}")
                continue
            except Exception as e:
                logger.warning(f"Error reading file {file_path}: {e}")
                continue

        return chunks

    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages."""
        return self.extractor.get_supported_languages()

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return self.extractor.get_supported_extensions()

    def is_supported_file(self, file_path: str) -> bool:
        """Check if a file is supported."""
        return self.extractor.is_supported_file(file_path)

    def _should_skip(self, file_path: Path) -> bool:
        """Check if file should be skipped based on default patterns (safety net for missing .gitignore)."""
        try:
            if hasattr(self, 'gitignore_parser') and self.gitignore_parser:
                rel_path = file_path.relative_to(self.gitignore_parser.repo_path)
                return should_ignore_by_default_patterns(str(rel_path))
        except (ValueError, AttributeError):
            pass
        
        # Fallback to using the full path
        return should_ignore_by_default_patterns(str(file_path))
