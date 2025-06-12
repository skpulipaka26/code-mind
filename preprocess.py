"""Turbo Review - Preprocessor

Parses a Git diff, extracts the changed AST nodes with Tree-sitter, and
emits self-contained JSON-serialisable CodeChunk objects that later stages
(can embed & retrieve) consume.

Intended usage
--------------
>>> from preprocessor import Preprocessor
>>> pr = Preprocessor(repo_root="/tmp/order-service")
>>> chunks = pr.run(diff_text)
>>> print(chunks[0])
CodeChunk(id='src/app.ts:42-47', file_path='src/app.ts', node_type='function', loc_range=(42, 47))
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path
from typing import List, Tuple

from pydantic import BaseModel
from unidiff import PatchSet
from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript

# ---------------------------------------------------------------------------
# Language setup using pre-compiled bindings
# ---------------------------------------------------------------------------
LANGUAGES = {
    "js": Language(tree_sitter_javascript.language()),
    "py": Language(tree_sitter_python.language()),
    "ts": Language(tree_sitter_typescript.language_typescript()),
    "tsx": Language(tree_sitter_typescript.language_tsx()),
}

PARSERS: dict[str, Parser] = {}
for ext, language in LANGUAGES.items():
    parser = Parser(language)
    PARSERS[ext] = parser

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
class CodeChunk(BaseModel):
    """Code chunk with AST node information and location data."""
    id: str
    file_path: str
    node_type: str
    code: str
    loc_range: Tuple[int, int]  # (start_line, end_line) inclusive

    def to_json(self) -> str:
        """Convert to JSON string using Pydantic's JSON serialization."""
        return self.model_dump_json()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class Preprocessor:
    """Generate AST-aligned code chunks from a diff."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).expanduser().resolve()
        if not (self.repo_root / ".git").exists():
            raise RuntimeError(f"{self.repo_root} is not a git repo")

    # Public API ----------------------------------------------------------------
    def run(self, diff: str) -> List[CodeChunk]:
        patch = PatchSet(diff)
        chunks: list[CodeChunk] = []
        for file in patch:
            abs_path = self.repo_root / file.path
            ext = abs_path.suffix.lstrip(".")
            parser = PARSERS.get(ext)
            if parser is None:
                continue  # unsupported language - skip for now

            # Retrieve pre-change file content at base commit ("from" SHA)
            self._cat_file(file.source_file, file.source_revision)
            new_blob = self._cat_file(file.target_file, file.target_revision)

            changed_lines = self._collect_changed_lines(file)
            if not changed_lines:
                continue

            tree = parser.parse(new_blob.encode())
            line_offsets = self._build_line_offsets(new_blob)

            self._collect_changed_nodes(
                tree.root_node, changed_lines, line_offsets, abs_path, new_blob, chunks
            )
        return chunks

    # Internals ------------------------------------------------------------------
    def _cat_file(self, path: str, rev: str | None) -> str:
        """Return file contents at a given Git revision (None → working tree)."""
        if rev is None or rev == "":  # working tree
            return (self.repo_root / path).read_text(encoding="utf-8")
        cmd = ["git", "-C", str(self.repo_root), "show", f"{rev}:{path}"]
        return subprocess.check_output(cmd, text=True)

    def _collect_changed_lines(self, file) -> set[int]:
        lines: set[int] = set()
        for hunk in file:
            start = hunk.target_start  # line numbers in *new* file
            for i, line in enumerate(hunk):
                if line.is_added or line.is_modified:
                    lines.add(start + i)
        return lines

    def _build_line_offsets(self, text: str) -> list[Tuple[int, int]]:
        """Return list of (byte_offset, line_no)."""
        offsets = [0]
        for m in re.finditer("\n", text):
            offsets.append(m.end())
        return offsets

    def _collect_changed_nodes(
        self,
        node,
        changed_lines: set[int],
        line_offsets: list[int],
        abs_path: Path,
        source: str,
        out: list[CodeChunk],
    ) -> None:
        start_line = node.start_point[0] + 1  # Tree‑sitter is 0‑indexed
        end_line = node.end_point[0] + 1

        # If node overlaps a changed line, recurse or record leaf
        if changed_lines.intersection(range(start_line, end_line + 1)):
            if node.child_count == 0 or node.type in {"function", "class", "method"}:
                code = source[node.start_byte : node.end_byte]
                out.append(
                    CodeChunk(
                        id=f"{abs_path}:{start_line}-{end_line}-{uuid.uuid4().hex[:6]}",
                        file_path=str(abs_path.relative_to(self.repo_root)),
                        node_type=node.type,
                        code=code,
                        loc_range=(start_line, end_line),
                    )
                )
            else:
                for child in node.children:
                    self._collect_changed_nodes(
                        child, changed_lines, line_offsets, abs_path, source, out
                    )
