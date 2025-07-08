import numpy as np
from core.vectordb import VectorDatabase, VectorMetadata
from core.chunker import CodeChunk


def test_vector_database_creation():
    """Test vector database creation."""
    db = VectorDatabase(dimension=384)

    assert db.dimension == 384
    assert len(db.metadata) == 0
    assert db.index.ntotal == 0


def test_add_chunks():
    """Test adding chunks to database."""
    db = VectorDatabase(dimension=384)

    # Create test chunks
    chunks = [
        CodeChunk(
            content="def hello(): print('hi')",
            file_path="test.py",
            start_line=1,
            end_line=2,
            chunk_type="function",
            name="hello",
        ),
        CodeChunk(
            content="class MyClass: pass",
            file_path="test.py",
            start_line=4,
            end_line=5,
            chunk_type="class",
            name="MyClass",
        ),
    ]

    # Create embeddings
    embeddings = [np.random.random(384).tolist(), np.random.random(384).tolist()]

    db.add_chunks(chunks, embeddings)

    assert len(db.metadata) == 2
    assert db.index.ntotal == 2
    assert len(db.chunk_contents) == 2


def test_search():
    """Test vector search."""
    db = VectorDatabase(dimension=384)

    # Add test data
    chunks = [
        CodeChunk(
            content="def hello(): print('hi')",
            file_path="test.py",
            start_line=1,
            end_line=2,
            chunk_type="function",
            name="hello",
        )
    ]

    embeddings = [np.random.random(384).tolist()]
    db.add_chunks(chunks, embeddings)

    # Search
    query_embedding = np.random.random(384).tolist()
    results = db.search(query_embedding, k=5)

    # Should return only 1 result since we only have 1 chunk
    # But FAISS may return up to k results with padding
    assert len(results) >= 1
    assert isinstance(results[0][0], VectorMetadata)
    assert isinstance(results[0][1], float)
    
    # Check that the first result is our actual chunk
    assert results[0][0].chunk_id == "test.py:1:2"


def test_get_content():
    """Test content retrieval."""
    db = VectorDatabase(dimension=384)

    chunk = CodeChunk(
        content="def hello(): print('hi')",
        file_path="test.py",
        start_line=1,
        end_line=2,
        chunk_type="function",
        name="hello",
    )

    embeddings = [np.random.random(384).tolist()]
    db.add_chunks([chunk], embeddings)

    chunk_id = "test.py:1:2"
    content = db.get_content(chunk_id)

    assert content == "def hello(): print('hi')"


def test_stats():
    """Test database statistics."""
    db = VectorDatabase(dimension=384)

    chunks = [
        CodeChunk(
            content="def hello(): pass",
            file_path="test.py",
            start_line=1,
            end_line=2,
            chunk_type="function",
            name="hello",
            language="python",
        ),
        CodeChunk(
            content="function greet() {}",
            file_path="test.js",
            start_line=1,
            end_line=1,
            chunk_type="function",
            name="greet",
            language="javascript",
        ),
    ]

    embeddings = [np.random.random(384).tolist(), np.random.random(384).tolist()]

    db.add_chunks(chunks, embeddings)

    stats = db.stats()

    assert stats["total_chunks"] == 2
    assert stats["dimension"] == 384
    assert "python" in stats["languages"]
    assert "javascript" in stats["languages"]
    assert "function" in stats["chunk_types"]


def test_save_load():
    """Test saving and loading database."""
    db = VectorDatabase(dimension=384)

    chunk = CodeChunk(
        content="def hello(): pass",
        file_path="test.py",
        start_line=1,
        end_line=2,
        chunk_type="function",
        name="hello",
    )

    embeddings = [np.random.random(384).tolist()]
    db.add_chunks([chunk], embeddings)

    # Save
    db.save("test_index")

    # Load into new database
    new_db = VectorDatabase(dimension=384)
    new_db.load("test_index")

    assert len(new_db.metadata) == 1
    assert new_db.index.ntotal == 1
    assert len(new_db.chunk_contents) == 1

    # Cleanup
    import os

    os.remove("test_index.faiss")
    os.remove("test_index.pkl")
