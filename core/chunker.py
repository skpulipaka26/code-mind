from typing import List, Optional
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Parser, Node
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript

from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CodeChunk:
    content: str
    file_path: str
    start_line: int
    end_line: int
    chunk_type: str
    name: Optional[str] = None
    language: str = "python"
    parent_name: Optional[str] = None
    parent_type: Optional[str] = None
    full_signature: Optional[str] = None
    docstring: Optional[str] = None


class TreeSitterChunker:
    """Extract code chunks using Tree-sitter."""

    def __init__(self):
        self.languages = {}
        self.parsers = {}

        # Initialize Python parser
        try:
            self.languages["python"] = Language(tspython.language())
            logger.debug("Python parser initialized.")
        except Exception as e:
            logger.warning(f"Could not initialize Python parser: {e}")

        # Initialize JavaScript parser
        try:
            self.languages["javascript"] = Language(tsjavascript.language())
            logger.debug("JavaScript parser initialized.")
        except Exception as e:
            logger.warning(f"Could not initialize JavaScript parser: {e}")

        # Initialize TypeScript parser (try different APIs)
        try:
            if hasattr(tstypescript, "language"):
                self.languages["typescript"] = Language(tstypescript.language())
            elif hasattr(tstypescript, "language_typescript"):
                self.languages["typescript"] = Language(
                    tstypescript.language_typescript()
                )
            logger.debug("TypeScript parser initialized.")
        except Exception as e:
            logger.warning(f"Could not initialize TypeScript parser: {e}")

        # Create parsers for available languages
        for lang, language in self.languages.items():
            try:
                self.parsers[lang] = Parser(language)
            except Exception:
                pass

    def chunk_file(self, file_path: str, content: str) -> List[CodeChunk]:
        """Extract chunks from a file."""
        language = self._detect_language(file_path)
        if language not in self.parsers:
            logger.warning(f"No parser available for language: {language}")
            return []

        parser = self.parsers[language]
        tree = parser.parse(bytes(content, "utf8"))
        chunks = []
        self._extract_chunks(
            tree.root_node,
            content,
            file_path,
            language,
            chunks,
            parent_name=None,
            parent_type=None,
        )
        return chunks

    def chunk_repository(self, repo_path: str) -> List[CodeChunk]:
        """Extract chunks from repository."""
        chunks = []
        repo_path = Path(repo_path)

        for ext in [".py", ".js", ".ts", ".tsx"]:
            for file_path in repo_path.rglob(f"*{ext}"):
                if self._should_skip(file_path):
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

    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension."""
        ext = Path(file_path).suffix.lower()
        if ext == ".py":
            return "python"
        elif ext in [".js", ".jsx"]:
            return "javascript"
        elif ext in [".ts", ".tsx"]:
            return "typescript"
        return "python"

    def _extract_chunks(
        self,
        node: Node,
        content: str,
        file_path: str,
        language: str,
        chunks: List[CodeChunk],
        parent_name: Optional[str] = None,
        parent_type: Optional[str] = None,
    ):
        """Extract chunks from AST node."""
        if language == "python":
            self._extract_python_chunks(
                node,
                content,
                file_path,
                chunks,
                parent_name=parent_name,
                parent_type=parent_type,
            )
        elif language in ["javascript", "typescript"]:
            self._extract_js_chunks(
                node,
                content,
                file_path,
                chunks,
                parent_name=parent_name,
                parent_type=parent_type,
            )

    def _extract_python_chunks(
        self,
        node: Node,
        content: str,
        file_path: str,
        chunks: List[CodeChunk],
        parent_name: Optional[str] = None,
        parent_type: Optional[str] = None,
    ):
        """Extract Python chunks."""
        current_parent_name = parent_name
        current_parent_type = parent_type

        if node.type == "function_definition":
            name = self._extract_name(node, content)
            chunk = self._create_chunk(
                node,
                content,
                file_path,
                "python",
                "function",
                parent_name=parent_name,
                parent_type=parent_type,
            )
            if chunk:
                chunks.append(chunk)
            current_parent_name = name
            current_parent_type = "function"

        elif node.type == "class_definition":
            name = self._extract_name(node, content)
            chunk = self._create_chunk(
                node,
                content,
                file_path,
                "python",
                "class",
                parent_name=parent_name,
                parent_type=parent_type,
            )
            if chunk:
                chunks.append(chunk)
            current_parent_name = name
            current_parent_type = "class"

        elif node.type in ["import_statement", "import_from_statement"]:
            chunk = self._create_chunk(
                node,
                content,
                file_path,
                "python",
                "import",
                parent_name=parent_name,
                parent_type=parent_type,
            )
            if chunk:
                chunks.append(chunk)

        for child in node.children:
            self._extract_python_chunks(
                child,
                content,
                file_path,
                chunks,
                parent_name=current_parent_name,
                parent_type=current_parent_type,
            )

    def _extract_js_chunks(
        self,
        node: Node,
        content: str,
        file_path: str,
        chunks: List[CodeChunk],
        parent_name: Optional[str] = None,
        parent_type: Optional[str] = None,
    ):
        """Extract JavaScript/TypeScript chunks."""
        current_parent_name = parent_name
        current_parent_type = parent_type

        if node.type in [
            "function_declaration",
            "function_expression",
            "arrow_function",
        ]:
            name = self._extract_name(node, content)
            chunk = self._create_chunk(
                node,
                content,
                file_path,
                "javascript",
                "function",
                parent_name=parent_name,
                parent_type=parent_type,
            )
            if chunk:
                chunks.append(chunk)
            current_parent_name = name
            current_parent_type = "function"

        elif node.type == "class_declaration":
            name = self._extract_name(node, content)
            chunk = self._create_chunk(
                node,
                content,
                file_path,
                "javascript",
                "class",
                parent_name=parent_name,
                parent_type=parent_type,
            )
            if chunk:
                chunks.append(chunk)
            current_parent_name = name
            current_parent_type = "class"

        for child in node.children:
            self._extract_js_chunks(
                child,
                content,
                file_path,
                chunks,
                parent_name=current_parent_name,
                parent_type=current_parent_type,
            )

    def _create_chunk(
        self,
        node: Node,
        content: str,
        file_path: str,
        language: str,
        chunk_type: str,
        parent_name: Optional[str] = None,
        parent_type: Optional[str] = None,
    ) -> Optional[CodeChunk]:
        """Create chunk from AST node."""
        lines = content.split("\n")
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        if start_line > len(lines) or end_line > len(lines):
            return None

        chunk_content = "\n".join(lines[start_line - 1 : end_line])

        # Ensure chunk content is not empty
        if not chunk_content.strip():
            logger.debug(
                f"Skipping empty chunk in {file_path} from line {start_line} to {end_line}"
            )
            return None

        name = self._extract_name(node, content)
        full_signature = None
        docstring = None

        if chunk_type in ["function", "class"]:
            full_signature = self._extract_full_signature(node, content, language)
            docstring = self._extract_docstring(node, content, language)

        return CodeChunk(
            content=chunk_content,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            chunk_type=chunk_type,
            name=name,
            language=language,
            parent_name=parent_name,
            parent_type=parent_type,
            full_signature=full_signature,
            docstring=docstring,
        )

    def _extract_full_signature(
        self, node: Node, content: str, language: str
    ) -> Optional[str]:
        if language == "python":
            return self._extract_full_signature_python(node, content)
        elif language in ["javascript", "typescript"]:
            return self._extract_full_signature_js(node, content)
        return None

    def _extract_docstring(
        self, node: Node, content: str, language: str
    ) -> Optional[str]:
        if language == "python":
            return self._extract_docstring_python(node, content)
        elif language in ["javascript", "typescript"]:
            return self._extract_docstring_js(node, content)
        return None

    def _extract_full_signature_python(self, node: Node, content: str) -> Optional[str]:
        if node.type == "function_definition" or node.type == "class_definition":
            lines = content[node.start_byte : node.end_byte].split("\n")
            if lines:
                return lines[0].strip()
        return None

    def _extract_docstring_python(self, node: Node, content: str) -> Optional[str]:
        if node.type == "function_definition" or node.type == "class_definition":
            for child in node.children:
                if child.type == "expression_statement" and child.children:
                    expr_child = child.children[0]
                    if expr_child.type == "string":
                        docstring_content = content[
                            expr_child.start_byte : expr_child.end_byte
                        ]
                        if docstring_content.startswith(
                            '"""'
                        ) and docstring_content.endswith('"""'):
                            return docstring_content[3:-3].strip()
                        elif docstring_content.startswith(
                            "'''"
                        ) and docstring_content.endswith("'''"):
                            return docstring_content[3:-3].strip()
                        elif docstring_content.startswith(
                            '"'
                        ) and docstring_content.endswith('"'):
                            return docstring_content[1:-1].strip()
                        elif docstring_content.startswith(
                            "''"
                        ) and docstring_content.endswith("''"):
                            return docstring_content[1:-1].strip()
        return None

    def _extract_full_signature_js(self, node: Node, content: str) -> Optional[str]:
        if node.type in [
            "function_declaration",
            "function_expression",
            "arrow_function",
            "class_declaration",
        ]:
            lines = content[node.start_byte : node.end_byte].split("\n")
            if lines:
                return lines[0].strip()
        return None

    def _extract_docstring_js(self, node: Node, content: str) -> Optional[str]:
        if node.prev_sibling and node.prev_sibling.type == "comment":
            comment_content = content[
                node.prev_sibling.start_byte : node.prev_sibling.end_byte
            ]
            if comment_content.startswith("/**") and comment_content.endswith("*/"):
                cleaned_docstring = []
                for line in comment_content.split("\n"):
                    line = line.strip()
                    if line.startswith("/**"):
                        line = line[3:].strip()
                    if line.endswith("*/"):
                        line = line[:-2].strip()
                    if line.startswith("*"):
                        line = line[1:].strip()
                    if line:
                        cleaned_docstring.append(line)
                return "\n".join(cleaned_docstring).strip()
        return None

    def _extract_name(self, node: Node, content: str) -> Optional[str]:
        """Extract function/class name."""
        for child in node.children:
            if child.type == "identifier":
                return content[child.start_byte : child.end_byte]
        return None

    def _should_skip(self, file_path: Path) -> bool:
        """Check if file should be skipped based on directory patterns."""
        skip_dirs = {
            ".git",
            "__pycache__",
            "node_modules",
            "venv",
            "env",
            ".venv",
            "dist",
            "build",
            ".pytest_cache",
            "site-packages",
            "typings",
        }

        for part in file_path.parts:
            if part in skip_dirs:
                return True

        if "test" in file_path.name.lower():
            return True

        return False
