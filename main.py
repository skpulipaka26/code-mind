"""
Turbo Review - AI-powered code review system

Usage:
    python main.py <command> [options]

Commands:
    index <repo_path>     - Index a repository
    review <diff_file>    - Review a diff file
    serve                 - Start review server
"""

import sys
import asyncio
from pathlib import Path

from core.chunker import TreeSitterChunker
from core.vectordb import VectorDatabase
from inference.openrouter_client import OpenRouterClient
from processing.diff_processor import DiffProcessor
from processing.reranker import CodeReranker


async def index_repository(repo_path: str):
    """Index a repository for code review."""
    print(f"Indexing repository: {repo_path}")
    
    # Extract code chunks
    chunker = TreeSitterChunker()
    chunks = chunker.chunk_repository(repo_path)
    print(f"Found {len(chunks)} code chunks")
    
    # Generate embeddings
    async with OpenRouterClient() as client:
        contents = [chunk.content for chunk in chunks]
        embeddings = await client.embed_batch(contents)
        print(f"Generated {len(embeddings)} embeddings")
    
    # Store in vector database
    db = VectorDatabase()
    db.add_chunks(chunks, embeddings)
    db.save("index")
    print("Repository indexed successfully")


async def review_diff(diff_file: str):
    """Review a diff file."""
    print(f"Reviewing diff: {diff_file}")
    
    # Load diff
    diff_content = Path(diff_file).read_text()
    
    # Process diff
    processor = DiffProcessor()
    changed_chunks = processor.extract_changed_chunks(diff_content)
    query = processor.create_query_from_changes(changed_chunks)
    print(f"Found {len(changed_chunks)} changed chunks")
    
    # Load vector database
    db = VectorDatabase()
    db.load("index")
    
    # Search for related code
    async with OpenRouterClient() as client:
        query_embedding = await client.embed(query)
        search_results = db.search(query_embedding, k=10)
        
        # Rerank results
        reranker = CodeReranker(client)
        chunk_contents = {meta.chunk_id: db.get_content(meta.chunk_id) for meta, _ in search_results}
        reranked_results = await reranker.rerank_search_results(
            query, search_results, chunk_contents, top_k=5
        )
        
        # Generate review
        review_context = "\n".join([
            f"Related code: {result.metadata.name or 'unnamed'} in {result.metadata.file_path}"
            for result in reranked_results
        ])
        
        review_prompt = f"""
Review this code change:

{diff_content}

Related code context:
{review_context}

Provide a concise code review focusing on:
1. Potential bugs or issues
2. Code quality improvements
3. Best practices
"""
        
        review = await client.complete([
            {"role": "user", "content": review_prompt}
        ])
        
        print("\n" + "="*50)
        print("CODE REVIEW")
        print("="*50)
        print(review)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "index" and len(sys.argv) > 2:
        asyncio.run(index_repository(sys.argv[2]))
    elif command == "review" and len(sys.argv) > 2:
        asyncio.run(review_diff(sys.argv[2]))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()