from core.chunker import TreeSitterChunker


def test_chunk_python_function():
    """Test Python function chunking."""
    chunker = TreeSitterChunker()

    code = '''
def hello_world():
    """Say hello to the world."""
    print("Hello, World!")
    return "greeting"
'''

    chunks = chunker.chunk_file("test.py", code)

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "function"
    assert chunks[0].name == "hello_world"
    assert chunks[0].language == "python"
    assert "def hello_world():" in chunks[0].content


def test_chunk_python_class():
    """Test Python class chunking."""
    chunker = TreeSitterChunker()

    code = '''
class Calculator:
    """A simple calculator."""
    
    def add(self, a, b):
        return a + b
    
    def subtract(self, a, b):
        return a - b
'''

    chunks = chunker.chunk_file("test.py", code)

    # Should have class + 2 methods
    assert len(chunks) >= 1

    class_chunk = next(chunk for chunk in chunks if chunk.chunk_type == "class")
    assert class_chunk.name == "Calculator"
    assert class_chunk.language == "python"


def test_chunk_javascript_function():
    """Test JavaScript function chunking."""
    chunker = TreeSitterChunker()

    code = """
function greet(name) {
    return `Hello, ${name}!`;
}

const add = (a, b) => {
    return a + b;
};
"""

    chunks = chunker.chunk_file("test.js", code)

    assert len(chunks) == 2

    # Find the greet function
    greet_chunk = next(chunk for chunk in chunks if chunk.name == "greet")
    assert greet_chunk.chunk_type == "function"
    assert greet_chunk.language == "javascript"


def test_chunk_imports():
    """Test import statement chunking."""
    chunker = TreeSitterChunker()

    code = """
import os
from pathlib import Path
import numpy as np
"""

    chunks = chunker.chunk_file("test.py", code)

    # Should have 3 import chunks
    import_chunks = [chunk for chunk in chunks if chunk.chunk_type == "import"]
    assert len(import_chunks) == 3


def test_language_detection():
    """Test language detection from file extension."""
    chunker = TreeSitterChunker()

    assert chunker._detect_language("test.py") == "python"
    assert chunker._detect_language("test.js") == "javascript"
    assert chunker._detect_language("test.ts") == "typescript"
    assert chunker._detect_language("test.tsx") == "typescript"


def test_should_skip_file():
    """Test file skipping logic."""
    chunker = TreeSitterChunker()

    from pathlib import Path

    # Should skip test files
    assert chunker._should_skip(Path("test_something.py"))
    assert chunker._should_skip(Path("something_test.py"))

    # Should skip directories
    assert chunker._should_skip(Path("project/__pycache__/module.py"))
    assert chunker._should_skip(Path("project/node_modules/package.js"))

    # Should not skip regular files
    assert not chunker._should_skip(Path("project/main.py"))
