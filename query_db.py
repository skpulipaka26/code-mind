#!/usr/bin/env python3
"""
Simple database query tool for turbo-review

Usage:
    python query_db.py list-repos
    python query_db.py list-chunks [repo_name]
    python query_db.py search "your search query"
    python query_db.py show-chunk <chunk_id>
    python query_db.py clear-all
    python query_db.py clear-vector
    python query_db.py clear-graph
"""

import sys
import asyncio
from qdrant_client import QdrantClient
from services.codebase_service import CodebaseService
from storage.database import CodeMindDatabase
from storage.graph_store import Neo4jGraphStore
from config import Config


def list_repositories():
    """List all indexed repositories."""
    db = CodeMindDatabase()
    repos = db.list_repositories()
    
    print("=== INDEXED REPOSITORIES ===")
    for repo in repos:
        print(f"• {repo.repo_url}")
        print(f"  Chunks: {repo.chunk_count}")
        print()


def list_chunks(repo_filter=None):
    """List code chunks, optionally filtered by repository."""
    client = QdrantClient(host='localhost', port=6333)
    
    # Get all collections
    collections = client.get_collections()
    
    print("=== CODE CHUNKS ===")
    for collection in collections.collections:
        if repo_filter and repo_filter not in collection.name:
            continue
            
        print(f"\nCollection: {collection.name}")
        
        # Get functions and classes
        points = client.scroll(
            collection_name=collection.name,
            scroll_filter={
                'must': [
                    {
                        'key': 'chunk_type',
                        'match': {
                            'any': ['function', 'class']
                        }
                    }
                ]
            },
            limit=20,
            with_payload=True,
            with_vectors=False
        )
        
        for point in points[0]:
            payload = point.payload
            file_path = payload.get('file_path', '').split('/')[-1]
            print(f"  {payload.get('chunk_type', 'N/A').upper()}: {payload.get('name', 'N/A')}")
            print(f"    File: {file_path} (lines {payload.get('start_line')}-{payload.get('end_line')})")


async def search_code(query):
    """Search code using semantic similarity."""
    config = Config.load()
    service = CodebaseService(config)
    
    result = await service.search_codebase(
        query=query,
        max_results=10,
        score_threshold=0.1  # Lower threshold for UniXcoder
    )
    
    print(f"=== SEARCH RESULTS FOR: '{query}' ===")
    print(f"Found {len(result.chunks)} results in {result.duration:.2f}s")
    print()
    
    for i, chunk in enumerate(result.chunks, 1):
        file_path = chunk['file_path'].split('/')[-1]
        print(f"{i}. {chunk['chunk_type'].upper()}: {chunk['name']}")
        print(f"   File: {file_path}")
        print(f"   Score: {chunk['score']:.3f}")
        print(f"   Lines: {chunk['start_line']}-{chunk['end_line']}")
        
        # Show content preview for high-scoring results
        if chunk['score'] > 0.8:
            content = chunk['content'][:200].replace('\n', ' ')
            print(f"   Preview: {content}...")
        print()


def show_chunk(chunk_id):
    """Show full content of a specific chunk."""
    client = QdrantClient(host='localhost', port=6333)
    
    # Search across all collections
    collections = client.get_collections()
    
    for collection in collections.collections:
        try:
            point = client.retrieve(
                collection_name=collection.name,
                ids=[int(chunk_id)],
                with_payload=True,
                with_vectors=False
            )
            
            if point:
                payload = point[0].payload
                print(f"=== CHUNK {chunk_id} ===")
                print(f"Type: {payload.get('chunk_type', 'N/A')}")
                print(f"Name: {payload.get('name', 'N/A')}")
                print(f"File: {payload.get('file_path', 'N/A')}")
                print(f"Lines: {payload.get('start_line', 'N/A')}-{payload.get('end_line', 'N/A')}")
                print(f"Language: {payload.get('language', 'N/A')}")
                print("\n--- CONTENT ---")
                print(payload.get('content', 'No content'))
                return
        except Exception:
            continue
    
    print(f"Chunk {chunk_id} not found")


def clear_vector_db():
    """Clear all vector database collections."""
    client = QdrantClient(host='localhost', port=6333)
    
    try:
        collections = client.get_collections()
        print("=== CLEARING VECTOR DATABASE ===")
        
        for collection in collections.collections:
            print(f"Deleting collection: {collection.name}")
            client.delete_collection(collection.name)
        
        print("✅ Vector database cleared successfully")
        
    except Exception as e:
        print(f"❌ Error clearing vector database: {e}")


def clear_graph_db():
    """Clear all graph database data."""
    try:
        graph = Neo4jGraphStore()
        print("=== CLEARING GRAPH DATABASE ===")
        
        success = graph.clear_graph()
        if success:
            print("✅ Graph database cleared successfully")
        else:
            print("❌ Failed to clear graph database")
            
        graph.close()
        
    except Exception as e:
        print(f"❌ Error clearing graph database: {e}")


def clear_all_databases():
    """Clear both vector and graph databases."""
    print("=== CLEARING ALL DATABASES ===")
    print("⚠️  This will delete all indexed repositories and chunks!")
    
    # Ask for confirmation
    response = input("Are you sure? Type 'yes' to confirm: ")
    if response.lower() != 'yes':
        print("❌ Operation cancelled")
        return
    
    clear_vector_db()
    clear_graph_db()
    
    # Also clear the repository tracking in the main database
    try:
        db = CodeMindDatabase()
        # Clear repository records (this will cascade to chunks)
        repos = db.list_repositories()
        for repo in repos:
            print(f"Removing repository record: {repo.repo_url}")
            db.delete_repository(repo.repo_url)
        
        print("✅ All databases cleared successfully")
        print("💡 You can now re-index with a new embedding model")
        
    except Exception as e:
        print(f"❌ Error clearing repository records: {e}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    command = sys.argv[1]
    
    if command == "list-repos":
        list_repositories()
    elif command == "list-chunks":
        repo_filter = sys.argv[2] if len(sys.argv) > 2 else None
        list_chunks(repo_filter)
    elif command == "search" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        asyncio.run(search_code(query))
    elif command == "show-chunk" and len(sys.argv) > 2:
        chunk_id = sys.argv[2]
        show_chunk(chunk_id)
    elif command == "clear-all":
        clear_all_databases()
    elif command == "clear-vector":
        clear_vector_db()
    elif command == "clear-graph":
        clear_graph_db()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()