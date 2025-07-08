from typing import List
from dataclasses import dataclass
from pathlib import Path
import unidiff
from core.chunker import TreeSitterChunker, CodeChunk
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DiffHunk:
    file_path: str
    old_start: int
    new_start: int
    added_lines: List[str]
    removed_lines: List[str]


@dataclass
class ChangedChunk:
    chunk: CodeChunk
    change_type: str  # 'added', 'removed', 'modified'


class DiffProcessor:
    """Process PR diffs and extract changed code chunks."""

    def __init__(self):
        self.chunker = TreeSitterChunker()

    def process_diff(self, diff_content: str) -> List[DiffHunk]:
        """Parse unified diff into hunks."""
        try:
            patch_set = unidiff.PatchSet(diff_content)
            hunks = []

            for patched_file in patch_set:
                for hunk in patched_file:
                    added_lines = [
                        line.value.rstrip("\n") for line in hunk if line.is_added
                    ]
                    removed_lines = [
                        line.value.rstrip("\n") for line in hunk if line.is_removed
                    ]

                    diff_hunk = DiffHunk(
                        file_path=patched_file.path,
                        old_start=hunk.source_start,
                        new_start=hunk.target_start,
                        added_lines=added_lines,
                        removed_lines=removed_lines,
                    )
                    hunks.append(diff_hunk)

            return hunks
        except Exception as e:
            logger.error(f"Error processing diff: {e}")
            return []

    def extract_changed_chunks(
        self, diff_content: str, repo_path: str = None
    ) -> List[ChangedChunk]:
        """Extract code chunks that were changed."""
        hunks = self.process_diff(diff_content)
        changed_chunks = []

        for hunk in hunks:
            file_path = (
                Path(repo_path) / hunk.file_path if repo_path else Path(hunk.file_path)
            )

            if not file_path.exists():
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                file_chunks = self.chunker.chunk_file(str(file_path), content)

                # Find overlapping chunks
                for chunk in file_chunks:
                    if self._chunk_overlaps_hunk(chunk, hunk):
                        change_type = self._determine_change_type(hunk)
                        changed_chunks.append(
                            ChangedChunk(chunk=chunk, change_type=change_type)
                        )
            except Exception as e:
                logger.warning(f"Error processing file {file_path}: {e}")
                continue

        return changed_chunks

    def create_query_from_changes(self, changed_chunks: List[ChangedChunk]) -> str:
        """Create search query from changed chunks."""
        query_parts = []

        for changed_chunk in changed_chunks:
            chunk = changed_chunk.chunk
            if chunk.name:
                query_parts.append(chunk.name)
            query_parts.append(chunk.chunk_type)

        return " ".join(set(query_parts))

    def _chunk_overlaps_hunk(self, chunk: CodeChunk, hunk: DiffHunk) -> bool:
        """Check if chunk overlaps with diff hunk."""
        hunk_start = min(hunk.old_start, hunk.new_start)
        hunk_end = max(
            hunk.old_start + len(hunk.removed_lines),
            hunk.new_start + len(hunk.added_lines),
        )

        return chunk.start_line <= hunk_end and chunk.end_line >= hunk_start

    def _determine_change_type(self, hunk: DiffHunk) -> str:
        """Determine type of change."""
        if hunk.added_lines and not hunk.removed_lines:
            return "added"
        elif hunk.removed_lines and not hunk.added_lines:
            return "removed"
        else:
            return "modified"
