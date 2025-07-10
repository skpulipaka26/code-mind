"""
Fallback chunking strategies for unsupported languages.
"""

import re
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from pathlib import Path

from core.chunk_types import CodeChunk
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ChunkingConfig:
    """Configuration for fallback chunking strategies."""
    max_chunk_size: int = 100  # lines
    min_chunk_size: int = 10   # lines
    overlap_size: int = 5      # lines
    prefer_heuristic: bool = True


class FallbackChunker:
    """Fallback chunking strategies for unsupported languages."""
    
    # Common patterns across many programming languages
    FUNCTION_PATTERNS = [
        # C-style: type name(...) { or function name(...) {
        r'^\s*(?:(?:public|private|protected|static|async|export|const|let|var)\s+)*(?:function\s+)?(\w+)\s*\([^)]*\)\s*\{',
        # Python-style: def name(...):
        r'^\s*def\s+(\w+)\s*\([^)]*\)\s*:',
        # Ruby-style: def name
        r'^\s*def\s+(\w+)',
        # Rust-style: fn name(...) {
        r'^\s*(?:pub\s+)?fn\s+(\w+)\s*\([^)]*\)\s*\{',
        # Go-style: func name(...) {
        r'^\s*func\s+(?:\([^)]*\)\s+)?(\w+)\s*\([^)]*\)\s*\{',
        # Swift-style: func name(...) {
        r'^\s*(?:public|private|internal|fileprivate|open)?\s*func\s+(\w+)\s*\([^)]*\)\s*\{',
        # Kotlin-style: fun name(...) {
        r'^\s*(?:public|private|internal|protected)?\s*fun\s+(\w+)\s*\([^)]*\)\s*\{',
    ]
    
    CLASS_PATTERNS = [
        # C-style: class Name {
        r'^\s*(?:public|private|protected|export)?\s*class\s+(\w+)(?:\s*extends\s+\w+)?(?:\s*implements\s+[\w,\s]+)?\s*\{',
        # Python-style: class Name:
        r'^\s*class\s+(\w+)(?:\([^)]*\))?\s*:',
        # Rust-style: struct Name {
        r'^\s*(?:pub\s+)?struct\s+(\w+)\s*\{',
        # Go-style: type Name struct {
        r'^\s*type\s+(\w+)\s+struct\s*\{',
        # Swift-style: class/struct Name {
        r'^\s*(?:public|private|internal|fileprivate|open)?\s*(?:class|struct)\s+(\w+)(?:\s*:\s*[\w,\s]+)?\s*\{',
    ]
    
    # Comment patterns for different languages
    COMMENT_PATTERNS = {
        'c_style': [r'//.*', r'/\*.*?\*/'],
        'python_style': [r'#.*'],
        'shell_style': [r'#.*'],
        'sql_style': [r'--.*'],
        'html_style': [r'<!--.*?-->'],
    }
    
    def __init__(self, config: Optional[ChunkingConfig] = None):
        self.config = config or ChunkingConfig()
    
    def chunk_unsupported_file(self, file_path: str, content: str) -> List[CodeChunk]:
        """Main entry point for chunking unsupported files."""
        if not content.strip():
            return []
        
        # Try heuristic-based chunking first
        if self.config.prefer_heuristic:
            heuristic_chunks = self._heuristic_chunking(file_path, content)
            if heuristic_chunks:
                logger.debug(f"Used heuristic chunking for {file_path}: {len(heuristic_chunks)} chunks")
                return heuristic_chunks
        
        # Fall back to sliding window
        logger.debug(f"Using sliding window chunking for {file_path}")
        return self._sliding_window_chunking(file_path, content)
    
    def _heuristic_chunking(self, file_path: str, content: str) -> List[CodeChunk]:
        """Attempt to find functions and classes using common patterns."""
        lines = content.split('\n')
        chunks = []
        
        # Find functions and classes
        function_chunks = self._find_functions(lines, file_path, content)
        class_chunks = self._find_classes(lines, file_path, content)
        
        all_chunks = function_chunks + class_chunks
        
        # If we found some structured chunks, use them
        if all_chunks:
            # Sort by start line
            all_chunks.sort(key=lambda x: x.start_line)
            
            # Fill gaps with content chunks if they're large enough
            filled_chunks = self._fill_gaps_with_content(all_chunks, lines, file_path)
            return filled_chunks
        
        return []
    
    def _find_functions(self, lines: List[str], file_path: str, content: str) -> List[CodeChunk]:
        """Find function-like structures using regex patterns."""
        chunks = []
        
        for i, line in enumerate(lines):
            for pattern in self.FUNCTION_PATTERNS:
                match = re.match(pattern, line)
                if match:
                    function_name = match.group(1)
                    start_line = i + 1
                    
                    # Find the end of the function
                    end_line = self._find_block_end(lines, i, file_path)
                    
                    if end_line > start_line:
                        chunk_content = '\n'.join(lines[start_line-1:end_line])
                        
                        chunks.append(CodeChunk(
                            content=chunk_content,
                            file_path=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            chunk_type="function",
                            name=function_name,
                            language=self._guess_language(file_path),
                            full_signature=line.strip()
                        ))
                    break
        
        return chunks
    
    def _find_classes(self, lines: List[str], file_path: str, content: str) -> List[CodeChunk]:
        """Find class-like structures using regex patterns."""
        chunks = []
        
        for i, line in enumerate(lines):
            for pattern in self.CLASS_PATTERNS:
                match = re.match(pattern, line)
                if match:
                    class_name = match.group(1)
                    start_line = i + 1
                    
                    # Find the end of the class
                    end_line = self._find_block_end(lines, i, file_path)
                    
                    if end_line > start_line:
                        chunk_content = '\n'.join(lines[start_line-1:end_line])
                        
                        chunks.append(CodeChunk(
                            content=chunk_content,
                            file_path=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            chunk_type="class",
                            name=class_name,
                            language=self._guess_language(file_path),
                            full_signature=line.strip()
                        ))
                    break
        
        return chunks
    
    def _find_block_end(self, lines: List[str], start_idx: int, file_path: str) -> int:
        """Find the end of a code block using brace/indentation matching."""
        start_line = lines[start_idx]
        
        # Brace-based languages
        if '{' in start_line:
            return self._find_brace_end(lines, start_idx)
        
        # Indentation-based languages (Python, YAML, etc.)
        elif start_line.rstrip().endswith(':'):
            return self._find_indentation_end(lines, start_idx)
        
        # Default: look for empty line or next function/class
        return self._find_logical_end(lines, start_idx)
    
    def _find_brace_end(self, lines: List[str], start_idx: int) -> int:
        """Find matching closing brace."""
        brace_count = 0
        in_string = False
        string_char = None
        
        for i in range(start_idx, len(lines)):
            line = lines[i]
            
            for char in line:
                # Handle string literals
                if char in ['"', "'"] and not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char and in_string:
                    in_string = False
                    string_char = None
                elif not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            return i + 1
        
        # If no matching brace found, return reasonable default
        return min(start_idx + self.config.max_chunk_size, len(lines))
    
    def _find_indentation_end(self, lines: List[str], start_idx: int) -> int:
        """Find end of indented block."""
        if start_idx >= len(lines):
            return len(lines)
        
        base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
        
        for i in range(start_idx + 1, len(lines)):
            line = lines[i]
            if line.strip():  # Non-empty line
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= base_indent:
                    return i
        
        return len(lines)
    
    def _find_logical_end(self, lines: List[str], start_idx: int) -> int:
        """Find logical end using heuristics."""
        # Look for next function/class or empty lines
        for i in range(start_idx + 1, min(start_idx + self.config.max_chunk_size, len(lines))):
            line = lines[i].strip()
            
            # Empty line followed by non-empty might indicate end
            if not line and i + 1 < len(lines) and lines[i + 1].strip():
                # Check if next line looks like a new function/class
                next_line = lines[i + 1]
                for pattern in self.FUNCTION_PATTERNS + self.CLASS_PATTERNS:
                    if re.match(pattern, next_line):
                        return i
            
            # Hit another function/class definition
            for pattern in self.FUNCTION_PATTERNS + self.CLASS_PATTERNS:
                if re.match(pattern, line):
                    return i
        
        return min(start_idx + self.config.max_chunk_size, len(lines))
    
    def _fill_gaps_with_content(self, chunks: List[CodeChunk], lines: List[str], file_path: str) -> List[CodeChunk]:
        """Fill large gaps between structured chunks with content chunks."""
        if not chunks:
            return chunks
        
        filled_chunks = []
        last_end = 1
        
        for chunk in chunks:
            # If there's a significant gap, create a content chunk
            gap_size = chunk.start_line - last_end
            if gap_size >= self.config.min_chunk_size:
                gap_content = '\n'.join(lines[last_end-1:chunk.start_line-1])
                if gap_content.strip():
                    filled_chunks.append(CodeChunk(
                        content=gap_content,
                        file_path=file_path,
                        start_line=last_end,
                        end_line=chunk.start_line - 1,
                        chunk_type="content",
                        name=None,
                        language=self._guess_language(file_path)
                    ))
            
            filled_chunks.append(chunk)
            last_end = chunk.end_line + 1
        
        # Handle remaining content after last chunk
        if last_end < len(lines):
            remaining_content = '\n'.join(lines[last_end-1:])
            if remaining_content.strip():
                filled_chunks.append(CodeChunk(
                    content=remaining_content,
                    file_path=file_path,
                    start_line=last_end,
                    end_line=len(lines),
                    chunk_type="content",
                    name=None,
                    language=self._guess_language(file_path)
                ))
        
        return filled_chunks
    
    def _sliding_window_chunking(self, file_path: str, content: str) -> List[CodeChunk]:
        """Create overlapping chunks using sliding window approach."""
        lines = content.split('\n')
        chunks = []
        
        if len(lines) <= self.config.max_chunk_size:
            # File is small enough to be one chunk
            return [CodeChunk(
                content=content,
                file_path=file_path,
                start_line=1,
                end_line=len(lines),
                chunk_type="content",
                name=None,
                language=self._guess_language(file_path)
            )]
        
        # Create overlapping chunks
        step_size = self.config.max_chunk_size - self.config.overlap_size
        
        for i in range(0, len(lines), step_size):
            end_idx = min(i + self.config.max_chunk_size, len(lines))
            chunk_lines = lines[i:end_idx]
            
            if len(chunk_lines) >= self.config.min_chunk_size:
                chunk_content = '\n'.join(chunk_lines)
                chunks.append(CodeChunk(
                    content=chunk_content,
                    file_path=file_path,
                    start_line=i + 1,
                    end_line=end_idx,
                    chunk_type="content",
                    name=f"chunk_{len(chunks) + 1}",
                    language=self._guess_language(file_path)
                ))
            
            # If we've reached the end, break
            if end_idx >= len(lines):
                break
        
        return chunks
    
    def _guess_language(self, file_path: str) -> str:
        """Guess language from file extension."""
        ext = Path(file_path).suffix.lower()
        
        # Common mappings
        ext_to_lang = {
            '.c': 'c', '.h': 'c',
            '.cpp': 'cpp', '.cxx': 'cpp', '.cc': 'cpp', '.hpp': 'cpp',
            '.cs': 'csharp',
            '.php': 'php',
            '.rb': 'ruby',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.clj': 'clojure',
            '.hs': 'haskell',
            '.ml': 'ocaml',
            '.fs': 'fsharp',
            '.dart': 'dart',
            '.lua': 'lua',
            '.r': 'r',
            '.m': 'objective-c',
            '.pl': 'perl',
            '.sh': 'shell',
            '.bash': 'bash',
            '.zsh': 'zsh',
            '.fish': 'fish',
            '.ps1': 'powershell',
            '.sql': 'sql',
            '.html': 'html',
            '.xml': 'xml',
            '.css': 'css',
            '.scss': 'scss',
            '.less': 'less',
            '.json': 'json',
            '.yaml': 'yaml', '.yml': 'yaml',
            '.toml': 'toml',
            '.ini': 'ini',
            '.cfg': 'config',
            '.conf': 'config',
            '.md': 'markdown',
            '.tex': 'latex',
            '.dockerfile': 'dockerfile',
            '.makefile': 'makefile',
        }
        
        return ext_to_lang.get(ext, 'unknown')
    
    def get_stats(self) -> Dict[str, int]:
        """Get statistics about chunking configuration."""
        return {
            'max_chunk_size': self.config.max_chunk_size,
            'min_chunk_size': self.config.min_chunk_size,
            'overlap_size': self.config.overlap_size,
            'function_patterns': len(self.FUNCTION_PATTERNS),
            'class_patterns': len(self.CLASS_PATTERNS),
        }