"""
Generic code chunk extractor that works with any Tree-sitter supported language.
"""

from typing import List, Optional, Dict
from pathlib import Path

from tree_sitter import Node
from core.language_registry import get_language_registry, LanguageConfig
from core.fallback_chunker import FallbackChunker, ChunkingConfig
from core.chunk_types import CodeChunk
from utils.logging import get_logger

logger = get_logger(__name__)


class GenericChunkExtractor:
    """Generic chunk extractor that works with any supported language."""

    def __init__(self, fallback_config: Optional[ChunkingConfig] = None):
        self.registry = get_language_registry()
        self.fallback_chunker = FallbackChunker(fallback_config)

    def extract_chunks(self, file_path: str, content: str) -> List[CodeChunk]:
        """Extract code chunks from any supported language file."""
        language = self.registry.get_language_for_file(file_path)

        # Try Tree-sitter parsing first
        if language:
            parser = self.registry.get_parser(language)
            config = self.registry.get_config(language)

            if parser and config:
                try:
                    tree = parser.parse(content.encode("utf-8"))
                    chunks = []

                    # Extract different types of chunks
                    for chunk_type, node_types in config.node_types.items():
                        chunks.extend(
                            self._extract_chunks_by_type(
                                tree.root_node,
                                content,
                                file_path,
                                language,
                                chunk_type,
                                node_types,
                            )
                        )

                    if chunks:
                        logger.debug(
                            f"Tree-sitter parsing successful for {file_path}: {len(chunks)} chunks"
                        )
                        return chunks
                    else:
                        logger.debug(
                            f"Tree-sitter parsing found no chunks for {file_path}, trying fallback"
                        )

                except Exception as e:
                    logger.debug(
                        f"Tree-sitter parsing failed for {file_path}: {e}, trying fallback"
                    )

        # Fall back to heuristic/sliding window chunking
        logger.debug(f"Using fallback chunking for {file_path}")
        return self.fallback_chunker.chunk_unsupported_file(file_path, content)

    def _extract_chunks_by_type(
        self,
        root_node: Node,
        content: str,
        file_path: str,
        language: str,
        chunk_type: str,
        node_types: List[str],
    ) -> List[CodeChunk]:
        """Extract chunks of a specific type."""
        chunks = []
        lines = content.split("\n")

        def traverse(node: Node, parent_name: str = None, parent_type: str = None):
            # Check if this node matches our target types
            if node.type in node_types:
                chunk = self._create_chunk(
                    node,
                    content,
                    lines,
                    file_path,
                    language,
                    chunk_type,
                    parent_name,
                    parent_type,
                )
                if chunk:
                    chunks.append(chunk)

                    # For classes, continue traversing to find methods
                    if chunk_type == "class":
                        for child in node.children:
                            traverse(child, chunk.name, chunk_type)
                    return  # Don't traverse children for other types

            # Continue traversing
            for child in node.children:
                traverse(child, parent_name, parent_type)

        traverse(root_node)
        return chunks

    def _create_chunk(
        self,
        node: Node,
        content: str,
        lines: List[str],
        file_path: str,
        language: str,
        chunk_type: str,
        parent_name: str = None,
        parent_type: str = None,
    ) -> Optional[CodeChunk]:
        """Create a code chunk from a Tree-sitter node."""
        try:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1

            # Extract content
            chunk_content = "\n".join(lines[start_line - 1 : end_line])

            # Extract name
            name = self._extract_name(node, language)

            # Extract signature
            signature = self._extract_signature(node, content, language)

            # Extract docstring
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
                full_signature=signature,
                docstring=docstring,
            )

        except Exception as e:
            logger.warning(f"Error creating chunk from node {node.type}: {e}")
            return None

    def _extract_name(self, node: Node, language: str) -> Optional[str]:
        """Extract the name of a code element."""
        # Common patterns for finding names
        name_fields = ["name", "identifier", "property_identifier"]

        for field in name_fields:
            name_node = node.child_by_field_name(field)
            if name_node:
                return name_node.text.decode("utf-8")

        # Fallback: look for identifier children
        for child in node.children:
            if child.type in ["identifier", "property_identifier", "type_identifier"]:
                return child.text.decode("utf-8")

        return None

    def _extract_signature(
        self, node: Node, content: str, language: str
    ) -> Optional[str]:
        """Extract the full signature of a function/method."""
        try:
            # For functions, try to get just the signature line
            if node.type in [
                "function_declaration",
                "function_definition",
                "method_definition",
            ]:
                lines = content.split("\n")
                start_line = node.start_point[0]

                # Look for the signature (usually first line or until opening brace/colon)
                signature_lines = []
                for i in range(start_line, min(start_line + 5, len(lines))):
                    line = lines[i].strip()
                    signature_lines.append(line)

                    # Stop at opening brace or colon (depending on language)
                    if language == "python" and line.endswith(":"):
                        break
                    elif (
                        language in ["javascript", "typescript", "c", "cpp", "java"]
                        and "{" in line
                    ):
                        break

                return " ".join(signature_lines)

            return None

        except Exception:
            return None

    def _extract_docstring(
        self, node: Node, content: str, language: str
    ) -> Optional[str]:
        """Extract docstring/comment for a code element."""
        try:
            config = self.registry.get_config(language)
            if not config:
                return None

            # Language-specific docstring extraction
            if language == "python":
                return self._extract_python_docstring(node, content)
            elif language in ["javascript", "typescript"]:
                return self._extract_js_docstring(node, content)
            else:
                return self._extract_generic_comment(node, content, config)

        except Exception:
            return None

    def _extract_python_docstring(self, node: Node, content: str) -> Optional[str]:
        """Extract Python docstring."""
        # Look for string literal as first statement in function/class body
        for child in node.children:
            if child.type == "block":
                for stmt in child.children:
                    if stmt.type == "expression_statement":
                        expr = stmt.children[0] if stmt.children else None
                        if expr and expr.type == "string":
                            docstring = expr.text.decode("utf-8")
                            # Clean up the docstring
                            return docstring.strip('"""').strip("'''").strip()
        return None

    def _extract_js_docstring(self, node: Node, content: str) -> Optional[str]:
        """Extract JavaScript/TypeScript JSDoc comment."""
        lines = content.split("\n")
        start_line = node.start_point[0]

        # Look for JSDoc comment before the function
        for i in range(start_line - 1, max(0, start_line - 10), -1):
            line = lines[i].strip()
            if line.startswith("/**"):
                # Extract JSDoc comment
                comment_lines = []
                for j in range(i, start_line):
                    comment_line = lines[j].strip()
                    if comment_line.startswith("*"):
                        comment_line = comment_line[1:].strip()
                    comment_lines.append(comment_line)
                    if comment_line.endswith("*/"):
                        break
                return "\n".join(comment_lines)
            elif line and not line.startswith("//"):
                break

        return None

    def _extract_generic_comment(
        self, node: Node, content: str, config: LanguageConfig
    ) -> Optional[str]:
        """Extract generic comment for any language."""
        lines = content.split("\n")
        start_line = node.start_point[0]

        # Look for comments before the code element
        comment_lines = []
        for i in range(start_line - 1, max(0, start_line - 5), -1):
            line = lines[i].strip()

            # Check if line starts with any comment pattern
            is_comment = False
            for pattern in config.comment_patterns:
                if line.startswith(pattern):
                    is_comment = True
                    # Remove comment prefix
                    clean_line = line[len(pattern) :].strip()
                    comment_lines.insert(0, clean_line)
                    break

            if not is_comment and line:
                break

        return "\n".join(comment_lines) if comment_lines else None

    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages."""
        return self.registry.get_supported_languages()

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return self.registry.get_supported_extensions()

    def is_supported_file(self, file_path: str) -> bool:
        """Check if a file is supported (now always true with fallback)."""
        # With fallback chunking, we can handle any text file
        # Just check if it's a reasonable file extension
        ext = Path(file_path).suffix.lower()

        # Skip binary file extensions
        binary_extensions = {
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bin",
            ".obj",
            ".o",
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".ico",
            ".svg",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
            ".wav",
            ".flac",
            ".zip",
            ".tar",
            ".gz",
            ".rar",
            ".7z",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
        }

        return ext not in binary_extensions

    def has_tree_sitter_support(self, file_path: str) -> bool:
        """Check if a file has Tree-sitter parser support."""
        return self.registry.get_language_for_file(file_path) is not None

    def get_fallback_stats(self) -> Dict[str, int]:
        """Get statistics about fallback chunking configuration."""
        return self.fallback_chunker.get_stats()
