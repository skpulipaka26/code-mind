from typing import List, Dict, Optional
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser, Node

from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

from core.chunker import CodeChunk
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Symbol:
    """Represents a code symbol (function, class, variable)."""

    name: str
    symbol_type: str  # 'function', 'class', 'variable', 'import'
    file_path: str
    line_number: int
    definition: Optional[str] = None


@dataclass
class Dependency:
    """Represents a dependency relationship between code chunks."""

    source_chunk: str  # chunk_id
    target_chunk: str  # chunk_id
    dependency_type: str  # 'calls', 'imports', 'inherits', 'uses'
    symbol_name: str


class LSPResolver:
    """Resolve AST-based symbol dependencies and relationships using LSP and Tree-sitter."""

    # Language mappings for Tree-sitter
    LANGUAGE_MAPPINGS = {
        ".py": ("python", Language(tspython.language())),
        ".js": ("javascript", Language(tsjavascript.language())),
        ".jsx": ("javascript", Language(tsjavascript.language())),
        ".ts": ("typescript", Language(tstypescript.language_typescript())),
        ".tsx": ("typescript", Language(tstypescript.language_tsx())),
    }

    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.language_servers: Dict[str, LanguageServer] = {}
        self.parsers: Dict[str, Parser] = {}
        self.dependencies: List[Dependency] = []
        self._setup_parsers()

    def _setup_parsers(self):
        """Initialize Tree-sitter parsers for supported languages."""
        for ext, (lang_name, language) in self.LANGUAGE_MAPPINGS.items():
            if lang_name not in self.parsers:
                parser = Parser(language)
                self.parsers[lang_name] = parser

    def _detect_language(self, file_path: str) -> Optional[str]:
        """Detect the programming language based on file extension."""
        file_ext = Path(file_path).suffix.lower()
        if file_ext in self.LANGUAGE_MAPPINGS:
            return self.LANGUAGE_MAPPINGS[file_ext][0]
        return None

    def _get_parser(self, language: str) -> Optional[Parser]:
        """Get Tree-sitter parser for a language."""
        return self.parsers.get(language)

    async def analyze_repository(self, chunks: List[CodeChunk]):
        """Analyze repository and build symbol table and dependencies using Tree-sitter and LSP."""
        logger.info(f"Analyzing repository with Tree-sitter + LSP: {self.repo_path}")

        try:
            # Convert repo_path to absolute path
            abs_repo_path = str(Path(self.repo_path).resolve())
            logger.debug(f"Using absolute repo path: {abs_repo_path}")

            chunk_map = {
                f"{chunk.file_path}:{chunk.start_line}:{chunk.end_line}": chunk
                for chunk in chunks
            }

            # Group chunks by language and file for more efficient processing
            chunks_by_language = {}
            for chunk in chunks:
                detected_language = self._detect_language(chunk.file_path)
                if detected_language and self._get_parser(detected_language):
                    if detected_language not in chunks_by_language:
                        chunks_by_language[detected_language] = {}

                    if chunk.file_path not in chunks_by_language[detected_language]:
                        chunks_by_language[detected_language][chunk.file_path] = []
                    chunks_by_language[detected_language][chunk.file_path].append(chunk)

            files_analyzed = 0
            total_symbols = 0

            # Process each language separately with its own language server
            for language, files_dict in chunks_by_language.items():
                try:
                    await self._analyze_language(
                        language, files_dict, chunk_map, abs_repo_path
                    )
                    files_analyzed += len(files_dict)
                except Exception as e:
                    logger.warning(f"Failed to analyze {language} files: {e}")

            logger.info(
                f"Tree-sitter + LSP analysis complete: {len(self.dependencies)} dependencies found across {files_analyzed} files"
            )

            return {
                "symbols": total_symbols,
                "dependencies": len(self.dependencies),
                "files_analyzed": files_analyzed,
            }

        except Exception as e:
            logger.error(f"Tree-sitter + LSP analysis failed: {e}")
            return {
                "symbols": 0,
                "dependencies": len(self.dependencies),
                "files_analyzed": 0,
            }

    async def _analyze_language(
        self,
        language: str,
        files_dict: Dict[str, List[CodeChunk]],
        chunk_map: Dict[str, CodeChunk],
        abs_repo_path: str,
    ):
        """Analyze files for a specific language using its language server."""
        logger.debug(f"Starting analysis for {language} with {len(files_dict)} files")

        multilspy_config = MultilspyConfig.from_dict(
            {"code_language": language, "trace_lsp_communication": False}
        )
        multilspy_logger = MultilspyLogger()
        language_server = LanguageServer.create(
            multilspy_config, multilspy_logger, abs_repo_path
        )

        # Store the language server for this language
        self.language_servers[language] = language_server

        try:
            # Use the async context manager to start the server
            async with language_server.start_server():
                for file_path, file_chunks in files_dict.items():
                    try:
                        logger.debug(
                            f"Analyzing {language} file: {file_path} with {len(file_chunks)} chunks"
                        )
                        for chunk in file_chunks:
                            try:
                                await self._analyze_chunk(
                                    chunk, chunk_map, language, language_server
                                )
                            except Exception as chunk_error:
                                logger.debug(
                                    f"Failed to analyze chunk {chunk.file_path}:{chunk.start_line}: {chunk_error}"
                                )
                    except Exception as e:
                        logger.warning(f"Failed to analyze file {file_path}: {e}")
        finally:
            # Clean up the language server reference
            if language in self.language_servers:
                del self.language_servers[language]

    async def _analyze_chunk(
        self,
        chunk: CodeChunk,
        chunk_map: Dict[str, CodeChunk],
        language: str,
        language_server: LanguageServer,
    ):
        """Analyze a single chunk and find its dependencies using Tree-sitter and LSP."""
        relative_file_path = chunk.file_path
        logger.debug(
            f"Analyzing {language} chunk: {chunk.file_path}:{chunk.start_line}-{chunk.end_line}"
        )

        # Open the file in the language server
        try:
            language_server.open_file(relative_file_path)
        except Exception as e:
            logger.debug(f"Failed to open file {relative_file_path}: {e}")
            return

        # Parse the chunk content with Tree-sitter
        parser = self._get_parser(language)
        if not parser:
            logger.debug(f"No parser available for {language}")
            return

        try:
            tree = parser.parse(bytes(chunk.content, "utf8"))
            await self._analyze_ast_nodes(
                tree.root_node,
                chunk,
                chunk_map,
                relative_file_path,
                language,
                language_server,
            )
        except Exception as e:
            logger.debug(f"Failed to parse chunk with Tree-sitter: {e}")
            return

    async def _analyze_ast_nodes(
        self,
        node: Node,
        chunk: CodeChunk,
        chunk_map: Dict[str, CodeChunk],
        relative_file_path: str,
        language: str,
        language_server: LanguageServer,
    ):
        """Analyze AST nodes to find dependencies using Tree-sitter."""
        # Define node types we're interested in for each language
        node_types_of_interest = {
            "python": {
                "import_statement",
                "import_from_statement",
                "call",
                "attribute",
                "class_definition",
                "function_definition",
                "identifier",
            },
            "javascript": {
                "import_statement",
                "call_expression",
                "member_expression",
                "class_declaration",
                "function_declaration",
                "identifier",
                "new_expression",
            },
            "typescript": {
                "import_statement",
                "call_expression",
                "member_expression",
                "class_declaration",
                "function_declaration",
                "identifier",
                "new_expression",
            },
        }

        target_types = node_types_of_interest.get(language, set())

        # Recursively traverse the AST
        await self._traverse_node(
            node,
            chunk,
            chunk_map,
            relative_file_path,
            language,
            language_server,
            target_types,
        )

    async def _traverse_node(
        self,
        node: Node,
        chunk: CodeChunk,
        chunk_map: Dict[str, CodeChunk],
        relative_file_path: str,
        language: str,
        language_server: LanguageServer,
        target_types: set,
    ):
        """Recursively traverse AST nodes and extract dependencies."""
        if node.type in target_types:
            await self._process_node_by_type(
                node, chunk, chunk_map, relative_file_path, language, language_server
            )

        # Recursively process child nodes
        for child in node.children:
            await self._traverse_node(
                child,
                chunk,
                chunk_map,
                relative_file_path,
                language,
                language_server,
                target_types,
            )

    async def _process_node_by_type(
        self,
        node: Node,
        chunk: CodeChunk,
        chunk_map: Dict[str, CodeChunk],
        relative_file_path: str,
        language: str,
        language_server: LanguageServer,
    ):
        """Process specific node types to extract dependencies."""
        node_type = node.type

        # Get the symbol name from the node
        symbol_name = self._extract_symbol_name(node, language)
        if not symbol_name:
            return

        # Calculate line and character position (LSP uses 0-based indexing)
        line_num = (chunk.start_line - 1) + node.start_point[0]
        char_pos = node.start_point[1]

        # Determine dependency type based on node type
        dependency_type = self._get_dependency_type_from_node(node_type, language)

        if dependency_type:
            await self._find_and_add_dependency(
                chunk,
                symbol_name,
                line_num,
                char_pos,
                chunk_map,
                dependency_type,
                relative_file_path,
                language,
                language_server,
            )

    def _extract_symbol_name(self, node: Node, language: str) -> Optional[str]:
        """Extract symbol name from AST node."""
        try:
            if language == "python":
                if node.type in ["import_statement", "import_from_statement"]:
                    # Find the module name in import statements
                    for child in node.children:
                        if child.type == "dotted_name" or child.type == "identifier":
                            return child.text.decode("utf8")
                elif node.type in ["call", "attribute"]:
                    # Extract function/method name
                    if node.children:
                        return node.children[0].text.decode("utf8")
                elif node.type == "identifier":
                    return node.text.decode("utf8")

            elif language in ["javascript", "typescript"]:
                if node.type == "import_statement":
                    # Find the source in import statements
                    for child in node.children:
                        if child.type == "string":
                            return child.text.decode("utf8").strip("\"'")
                elif node.type in ["call_expression", "new_expression"]:
                    # Extract function name
                    if node.children:
                        return node.children[0].text.decode("utf8")
                elif node.type == "member_expression":
                    # Extract property name
                    if len(node.children) >= 3:
                        return node.children[2].text.decode("utf8")
                elif node.type == "identifier":
                    return node.text.decode("utf8")

        except Exception as e:
            logger.debug(f"Failed to extract symbol name from {node.type}: {e}")

        return None

    def _get_dependency_type_from_node(
        self, node_type: str, language: str
    ) -> Optional[str]:
        """Map AST node types to dependency types."""
        type_mappings = {
            "python": {
                "import_statement": "imports",
                "import_from_statement": "imports",
                "call": "calls",
                "attribute": "uses",
                "identifier": "uses",
            },
            "javascript": {
                "import_statement": "imports",
                "call_expression": "calls",
                "new_expression": "instantiates",
                "member_expression": "uses",
                "identifier": "uses",
            },
            "typescript": {
                "import_statement": "imports",
                "call_expression": "calls",
                "new_expression": "instantiates",
                "member_expression": "uses",
                "identifier": "uses",
            },
        }

        return type_mappings.get(language, {}).get(node_type)

    async def _process_document_symbols(
        self, symbols: list, chunk: CodeChunk, chunk_map: Dict[str, CodeChunk]
    ):
        """Process document symbols to find structural dependencies."""
        for symbol in symbols:
            if symbol.get("children"):
                await self._process_document_symbols(
                    symbol["children"], chunk, chunk_map
                )

    async def _find_and_add_dependency(
        self,
        source_chunk: CodeChunk,
        symbol_name: str,
        line_num: int,
        char_pos: int,
        chunk_map: Dict[str, CodeChunk],
        dependency_type: str,
        relative_file_path: str,
        language: str,
        language_server: LanguageServer,
    ):
        """Find the definition of a symbol and add it as a dependency."""
        # Skip common keywords and built-ins (Tree-sitter handles this better than manual lists)
        if len(symbol_name) <= 2 or symbol_name.isdigit():
            return

        source_chunk_id = f"{source_chunk.file_path}:{source_chunk.start_line}:{source_chunk.end_line}"

        try:
            # Try to get definition using LSP
            definitions = await language_server.request_definition(
                relative_file_path, line_num, char_pos
            )

            for definition in definitions:
                # Handle different response formats from LSP
                if hasattr(definition, "uri"):
                    # Location object format
                    uri = definition.uri
                    line = definition.range.start.line
                elif isinstance(definition, dict):
                    # Dictionary format
                    uri = definition.get("uri")
                    range_info = definition.get("range", {})
                    start_info = range_info.get("start", {})
                    line = start_info.get("line", 0)
                else:
                    logger.debug(f"Unknown definition format: {type(definition)}")
                    continue

                if not uri:
                    logger.debug(f"No URI in definition: {definition}")
                    continue

                target_chunk = self._find_chunk_for_location(uri, line, chunk_map)

                if target_chunk:
                    target_chunk_id = f"{target_chunk.file_path}:{target_chunk.start_line}:{target_chunk.end_line}"

                    # Avoid self-dependencies
                    if source_chunk_id == target_chunk_id:
                        continue

                    # Refine dependency type based on target chunk type
                    refined_type = self._refine_dependency_type(
                        dependency_type, target_chunk
                    )

                    dep = Dependency(
                        source_chunk=source_chunk_id,
                        target_chunk=target_chunk_id,
                        dependency_type=refined_type,
                        symbol_name=symbol_name,
                    )

                    # Check if dependency already exists
                    if not any(
                        existing.source_chunk == dep.source_chunk
                        and existing.target_chunk == dep.target_chunk
                        and existing.symbol_name == dep.symbol_name
                        for existing in self.dependencies
                    ):
                        self.dependencies.append(dep)
                        logger.debug(
                            f"Added {language} dependency: {source_chunk.file_path}:{source_chunk.start_line} {refined_type} {target_chunk.file_path}:{target_chunk.start_line} ({symbol_name})"
                        )

        except Exception as e:
            # Log debug info for failed lookups, but don't fail the analysis
            logger.debug(
                f"Failed to find definition for {symbol_name} at {source_chunk.file_path}:{line_num}:{char_pos}: {e}"
            )

    def _refine_dependency_type(self, base_type: str, target_chunk: CodeChunk) -> str:
        """Refine the dependency type based on the target chunk type."""
        if base_type == "calls" and target_chunk.chunk_type in [
            "function_definition",
            "method_definition",
        ]:
            return "calls"
        elif (
            base_type == "instantiates"
            and target_chunk.chunk_type == "class_definition"
        ):
            return "instantiates"
        elif base_type == "inherits" and target_chunk.chunk_type == "class_definition":
            return "inherits"
        elif base_type == "imports":
            return "imports"
        else:
            return "uses"

    def get_dependencies_for_chunk(self, chunk_id: str) -> List[Dependency]:
        """Get all dependencies for a specific chunk."""
        return [dep for dep in self.dependencies if dep.source_chunk == chunk_id]

    def get_dependents_for_chunk(self, chunk_id: str) -> List[Dependency]:
        """Get all chunks that depend on a specific chunk."""
        return [dep for dep in self.dependencies if dep.target_chunk == chunk_id]

    def get_dependency_graph_stats(self) -> Dict[str, int]:
        """Get statistics about the dependency graph."""
        stats = {
            "total_dependencies": len(self.dependencies),
            "calls": len(
                [d for d in self.dependencies if d.dependency_type == "calls"]
            ),
            "imports": len(
                [d for d in self.dependencies if d.dependency_type == "imports"]
            ),
            "inherits": len(
                [d for d in self.dependencies if d.dependency_type == "inherits"]
            ),
            "instantiates": len(
                [d for d in self.dependencies if d.dependency_type == "instantiates"]
            ),
            "uses": len([d for d in self.dependencies if d.dependency_type == "uses"]),
        }
        return stats

    def _find_chunk_for_location(
        self, file_uri: str, line: int, chunk_map: Dict[str, CodeChunk]
    ) -> Optional[CodeChunk]:
        """Find the chunk that contains the given location."""
        # multilspy returns file URIs, convert back to relative path
        if file_uri.startswith("file://"):
            file_path = Path(file_uri.replace("file://", "")).as_posix()
            # Make it relative to the repo root
            repo_root = Path(self.repo_path).resolve()
            try:
                file_path = str(Path(file_path).relative_to(repo_root))
            except ValueError:
                # If not relative to repo root, use as-is
                pass
        else:
            file_path = file_uri

        # Convert LSP 0-based line to 1-based line for chunk comparison
        line_1_based = line + 1

        for chunk_id, chunk in chunk_map.items():
            if chunk.file_path == file_path:
                if chunk.start_line <= line_1_based <= chunk.end_line:
                    return chunk
        return None
