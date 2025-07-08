import re
from typing import List, Set, Dict, Optional
from dataclasses import dataclass
from pathlib import Path

from core.chunker import TreeSitterChunker, CodeChunk
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


class ASTResolver:
    """Resolve AST-based symbol dependencies and relationships."""

    def __init__(self):
        self.chunker = TreeSitterChunker()
        self.symbol_table: Dict[str, List[Symbol]] = {}
        self.dependencies: List[Dependency] = []

    def analyze_repository(self, repo_path: str) -> Dict[str, any]:
        """Analyze repository and build symbol table and dependencies."""
        logger.info(f"Analyzing repository: {repo_path}")
        repo_path = Path(repo_path)

        # Extract all chunks with symbols
        chunks = self.chunker.chunk_repository(str(repo_path))

        # Build symbol table
        self._build_symbol_table(chunks)

        # Find dependencies
        self._find_dependencies(chunks)

        return {
            "symbols": len(self.symbol_table),
            "dependencies": len(self.dependencies),
            "files_analyzed": len(set(chunk.file_path for chunk in chunks)),
        }

    def find_related_chunks(self, chunk_ids: List[str], max_depth: int = 2) -> Set[str]:
        """Find chunks related to given chunks through dependencies."""
        related = set(chunk_ids)
        current_level = set(chunk_ids)

        for depth in range(max_depth):
            next_level = set()

            for dependency in self.dependencies:
                if dependency.source_chunk in current_level:
                    next_level.add(dependency.target_chunk)
                elif dependency.target_chunk in current_level:
                    next_level.add(dependency.source_chunk)

            new_chunks = next_level - related
            if not new_chunks:
                break

            related.update(new_chunks)
            current_level = new_chunks

        return related

    def get_symbols_in_chunk(self, chunk: CodeChunk) -> List[Symbol]:
        """Extract symbols defined in a code chunk."""
        symbols = []

        if chunk.language == "python":
            symbols.extend(self._extract_python_symbols(chunk))
        elif chunk.language in ["javascript", "typescript"]:
            symbols.extend(self._extract_js_symbols(chunk))

        return symbols

    def get_imported_symbols(self, chunk: CodeChunk) -> List[str]:
        """Get symbols imported by a code chunk."""
        imported = []

        if chunk.chunk_type == "import":
            if chunk.language == "python":
                imported.extend(self._extract_python_imports(chunk.content))
            elif chunk.language in ["javascript", "typescript"]:
                imported.extend(self._extract_js_imports(chunk.content))

        return imported

    def get_called_functions(self, chunk: CodeChunk) -> List[str]:
        """Get function calls within a code chunk."""
        calls = []

        if chunk.language == "python":
            calls.extend(self._extract_python_calls(chunk.content))
        elif chunk.language in ["javascript", "typescript"]:
            calls.extend(self._extract_js_calls(chunk.content))

        return calls

    def _build_symbol_table(self, chunks: List[CodeChunk]):
        """Build symbol table from chunks."""
        self.symbol_table = {}

        for chunk in chunks:
            symbols = self.get_symbols_in_chunk(chunk)

            for symbol in symbols:
                if symbol.name not in self.symbol_table:
                    self.symbol_table[symbol.name] = []
                self.symbol_table[symbol.name].append(symbol)

    def _find_dependencies(self, chunks: List[CodeChunk]):
        """Find dependencies between chunks."""
        self.dependencies = []

        for chunk in chunks:
            chunk_id = f"{chunk.file_path}:{chunk.start_line}:{chunk.end_line}"

            # Find import dependencies
            imported_symbols = self.get_imported_symbols(chunk)
            for symbol_name in imported_symbols:
                if symbol_name in self.symbol_table:
                    for target_symbol in self.symbol_table[symbol_name]:
                        target_chunk_id = (
                            f"{target_symbol.file_path}:{target_symbol.line_number}"
                        )

                        dependency = Dependency(
                            source_chunk=chunk_id,
                            target_chunk=target_chunk_id,
                            dependency_type="imports",
                            symbol_name=symbol_name,
                        )
                        self.dependencies.append(dependency)

            # Find function call dependencies
            called_functions = self.get_called_functions(chunk)
            for function_name in called_functions:
                if function_name in self.symbol_table:
                    for target_symbol in self.symbol_table[function_name]:
                        if target_symbol.symbol_type == "function":
                            target_chunk_id = (
                                f"{target_symbol.file_path}:{target_symbol.line_number}"
                            )

                            dependency = Dependency(
                                source_chunk=chunk_id,
                                target_chunk=target_chunk_id,
                                dependency_type="calls",
                                symbol_name=function_name,
                            )
                            self.dependencies.append(dependency)

    def _extract_python_symbols(self, chunk: CodeChunk) -> List[Symbol]:
        """Extract symbols from Python code chunk."""
        symbols = []

        if chunk.chunk_type == "function" and chunk.name:
            symbols.append(
                Symbol(
                    name=chunk.name,
                    symbol_type="function",
                    file_path=chunk.file_path,
                    line_number=chunk.start_line,
                    definition=chunk.content,
                )
            )

        elif chunk.chunk_type == "class" and chunk.name:
            symbols.append(
                Symbol(
                    name=chunk.name,
                    symbol_type="class",
                    file_path=chunk.file_path,
                    line_number=chunk.start_line,
                    definition=chunk.content,
                )
            )

        return symbols

    def _extract_js_symbols(self, chunk: CodeChunk) -> List[Symbol]:
        """Extract symbols from JavaScript/TypeScript code chunk."""
        symbols = []

        if chunk.chunk_type == "function" and chunk.name:
            symbols.append(
                Symbol(
                    name=chunk.name,
                    symbol_type="function",
                    file_path=chunk.file_path,
                    line_number=chunk.start_line,
                    definition=chunk.content,
                )
            )

        elif chunk.chunk_type == "class" and chunk.name:
            symbols.append(
                Symbol(
                    name=chunk.name,
                    symbol_type="class",
                    file_path=chunk.file_path,
                    line_number=chunk.start_line,
                    definition=chunk.content,
                )
            )

        return symbols

    def _extract_python_imports(self, content: str) -> List[str]:
        """Extract imported symbols from Python import statements using regex patterns."""
        imported = []

        # Simple regex-based extraction for common patterns

        # from module import symbol1, symbol2
        from_imports = re.findall(r"from\s+[\w.]+\s+import\s+([\w\s,]+)", content)
        for match in from_imports:
            symbols = [s.strip() for s in match.split(",")]
            imported.extend(symbols)

        # import module as alias
        direct_imports = re.findall(r"import\s+([\w.]+)(?:\s+as\s+(\w+))?", content)
        for match in direct_imports:
            module_name = match[0]
            alias = match[1] if match[1] else module_name.split(".")[-1]
            imported.append(alias)

        return imported

    def _extract_js_imports(self, content: str) -> List[str]:
        """Extract imported symbols from JavaScript/TypeScript import statements using regex patterns."""
        imported = []

        # import { symbol1, symbol2 } from 'module'
        named_imports = re.findall(r"import\s*\{\s*([\w\s,]+)\s*\}\s*from", content)
        for match in named_imports:
            symbols = [s.strip() for s in match.split(",")]
            imported.extend(symbols)

        # import symbol from 'module'
        default_imports = re.findall(r"import\s+(\w+)\s+from", content)
        imported.extend(default_imports)

        return imported

    def _extract_python_calls(self, content: str) -> List[str]:
        """Extract function calls from Python code using regex patterns, filtering out keywords."""
        calls = []

        # Simple function call pattern: function_name(
        function_calls = re.findall(r"(\w+)\s*\(", content)

        # Filter out keywords and built-ins
        python_keywords = {
            "if",
            "for",
            "while",
            "def",
            "class",
            "return",
            "import",
            "from",
            "try",
            "except",
            "with",
            "as",
            "print",
            "len",
            "str",
            "int",
            "float",
            "list",
            "dict",
            "set",
            "tuple",
            "bool",
            "range",
            "enumerate",
            "zip",
        }

        for call in function_calls:
            if call not in python_keywords and len(call) > 1:
                calls.append(call)

        return list(set(calls))  # Remove duplicates

    def _extract_js_calls(self, content: str) -> List[str]:
        """Extract function calls from JavaScript/TypeScript code using regex patterns, filtering out keywords."""
        calls = []

        # Function call pattern: function_name(
        function_calls = re.findall(r"(\w+)\s*\(", content)

        # Filter out keywords and built-ins
        js_keywords = {
            "if",
            "for",
            "while",
            "function",
            "class",
            "return",
            "import",
            "from",
            "try",
            "catch",
            "console",
            "parseInt",
            "parseFloat",
            "String",
            "Number",
            "Array",
            "Object",
            "Boolean",
            "typeof",
            "instanceof",
        }

        for call in function_calls:
            if call not in js_keywords and len(call) > 1:
                calls.append(call)

        return list(set(calls))  # Remove duplicates
