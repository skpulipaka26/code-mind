"""
Common data types for code chunking.
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class CodeChunk:
    content: str
    file_path: str
    start_line: int
    end_line: int
    chunk_type: str
    name: Optional[str] = None
    language: str = "unknown"
    parent_name: Optional[str] = None
    parent_type: Optional[str] = None
    full_signature: Optional[str] = None
    docstring: Optional[str] = None