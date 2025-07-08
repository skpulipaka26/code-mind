import asyncio
import time
from pathlib import Path
from typing import Optional

import click

from core.chunker import TreeSitterChunker
from core.vectordb import VectorDatabase
from inference.openrouter_client import OpenRouterClient
from processing.diff_processor import DiffProcessor
from processing.reranker import CodeReranker
from cli.config import Config
from monitoring.telemetry import setup_telemetry, get_telemetry


@click.group()
@click.option("--config", "-c", help="Config file path")
@click.pass_context
def cli(ctx, config):
    """Turbo Review - AI-powered code review system."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.load(config)

    # Initialize telemetry
    setup_telemetry()


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--output", "-o", default="index", help="Output index name")
@click.pass_context
def index(ctx, repo_path: str, output: str):
    """Index a repository for code review."""
    asyncio.run(_index_repository(repo_path, output, ctx.obj["config"]))


@cli.command()
@click.argument("diff_file", type=click.Path(exists=True))
@click.option("--index", "-i", default="index", help="Index to use")
@click.option("--repo", "-r", help="Repository path")
@click.pass_context
def review(ctx, diff_file: str, index: str, repo: Optional[str]):
    """Review a diff file."""
    asyncio.run(_review_diff(diff_file, index, repo, ctx.obj["config"]))


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.argument("diff_file", type=click.Path(exists=True))
@click.pass_context
def quick(ctx, repo_path: str, diff_file: str):
    """Quick review without pre-indexing."""
    asyncio.run(_quick_review(repo_path, diff_file, ctx.obj["config"]))


async def _index_repository(repo_path: str, output: str, config: Config):
    """Index repository implementation."""
    telemetry = get_telemetry()

    with telemetry.trace_operation(
        "index_repository", {"repo_path": repo_path, "output": output}
    ):
        click.echo(f"🔍 Indexing repository: {repo_path}")

        # Extract code chunks
        with telemetry.trace_operation("extract_chunks"):
            chunker = TreeSitterChunker()
            chunks = chunker.chunk_repository(repo_path)

        click.echo(f"📄 Found {len(chunks)} code chunks")
        telemetry.update_chunk_count(
            len(chunks), {"operation": "index", "repo": repo_path}
        )

        if not chunks:
            click.echo("❌ No code chunks found. Check repository path.")
            return

        # Generate embeddings
        async with OpenRouterClient(api_key=config.openrouter_api_key) as client:
            try:
                with telemetry.trace_operation(
                    "generate_embeddings", {"chunk_count": len(chunks)}
                ):
                    embedding_start = time.time()
                    contents = [chunk.content for chunk in chunks]
                    with click.progressbar(
                        length=len(contents), label="Generating embeddings"
                    ) as bar:
                        embeddings = []
                        batch_size = 50
                        for i in range(0, len(contents), batch_size):
                            batch = contents[i : i + batch_size]
                            batch_embeddings = await client.embed_batch(batch)
                            embeddings.extend(batch_embeddings)
                            bar.update(len(batch))

                    embedding_duration = time.time() - embedding_start
                    telemetry.record_embedding_duration(
                        embedding_duration, {"chunk_count": len(chunks)}
                    )

                click.echo(f"🧠 Generated {len(embeddings)} embeddings")
            except Exception as e:
                click.echo(f"❌ Error generating embeddings: {e}")
                return

        # Store in vector database
        try:
            with telemetry.trace_operation("store_vectors"):
                db = VectorDatabase()
                db.add_chunks(chunks, embeddings)
                db.save(output)
            click.echo(f"✅ Repository indexed successfully as '{output}'")
        except Exception as e:
            click.echo(f"❌ Error saving index: {e}")


async def _review_diff(
    diff_file: str, index: str, repo_path: Optional[str], config: Config
):
    """Review diff implementation."""
    telemetry = get_telemetry()

    with telemetry.trace_operation(
        "review_diff", {"diff_file": diff_file, "index": index}
    ):
        review_start = time.time()
        click.echo(f"📝 Reviewing diff: {diff_file}")

        # Load diff
        try:
            diff_content = Path(diff_file).read_text()
        except Exception as e:
            click.echo(f"❌ Error reading diff file: {e}")
            return

        # Process diff
        with telemetry.trace_operation("process_diff"):
            processor = DiffProcessor()
            changed_chunks = processor.extract_changed_chunks(diff_content, repo_path)
        click.echo(f"🔧 Found {len(changed_chunks)} changed chunks")

        if not changed_chunks:
            click.echo("ℹ️  No code chunks changed. Creating generic review.")
            query = "code review"
        else:
            query = processor.create_query_from_changes(changed_chunks)

        # Load vector database
        try:
            with telemetry.trace_operation("load_index"):
                db = VectorDatabase()
                db.load(index)
            click.echo(f"📚 Loaded index '{index}' with {len(db.metadata)} chunks")
        except Exception as e:
            click.echo(f"❌ Error loading index '{index}': {e}")
            return

        # Search and review
        async with OpenRouterClient(api_key=config.openrouter_api_key) as client:
            try:
                # Search for related code
                with telemetry.trace_operation("vector_search"):
                    retrieval_start = time.time()
                    query_embedding = await client.embed(query)
                    search_results = db.search(query_embedding, k=10)
                    retrieval_duration = time.time() - retrieval_start
                    telemetry.record_retrieval_duration(
                        retrieval_duration, {"query_type": "diff_review"}
                    )

                if search_results:
                    # Rerank results
                    with telemetry.trace_operation("rerank_results"):
                        reranker = CodeReranker(client)
                        chunk_contents = {
                            meta.chunk_id: db.get_content(meta.chunk_id)
                            for meta, _ in search_results
                        }
                        reranked_results = await reranker.rerank_search_results(
                            query, search_results, chunk_contents, top_k=5
                        )

                    # Build context
                    context_parts = []
                    for result in reranked_results:
                        context_parts.append(f"File: {result.metadata.file_path}")
                        context_parts.append(f"Type: {result.metadata.chunk_type}")
                        if result.metadata.name:
                            context_parts.append(f"Name: {result.metadata.name}")
                        context_parts.append(
                            f"Code:\n{db.get_content(result.metadata.chunk_id)}"
                        )
                        context_parts.append("-" * 40)

                    review_context = "\n".join(context_parts)
                else:
                    review_context = "No related code found in index."

                # Generate review
                review_prompt = f"""Review this code change:

{diff_content}

Related code context:
{review_context}

Provide a concise code review focusing on:
1. Potential bugs or issues
2. Code quality improvements  
3. Best practices
4. Security considerations

Format your response with clear sections."""

                click.echo("🤖 Generating review...")
                with telemetry.trace_operation("generate_review"):
                    review = await client.complete(
                        [{"role": "user", "content": review_prompt}]
                    )

                # Record total review duration
                review_duration = time.time() - review_start
                telemetry.record_review_duration(
                    review_duration, {"diff_file": diff_file}
                )

                # Display review
                click.echo("\n" + "=" * 60)
                click.echo("📋 CODE REVIEW")
                click.echo("=" * 60)
                click.echo(review)
                click.echo("=" * 60)

            except Exception as e:
                click.echo(f"❌ Error during review: {e}")


async def _quick_review(repo_path: str, diff_file: str, config: Config):
    """Quick review without indexing."""
    click.echo(f"⚡ Quick review: {diff_file}")

    # Load diff
    try:
        diff_content = Path(diff_file).read_text()
    except Exception as e:
        click.echo(f"❌ Error reading diff file: {e}")
        return

    # Process diff to find changed files
    processor = DiffProcessor()
    changed_chunks = processor.extract_changed_chunks(diff_content, repo_path)

    # Get related files from repository
    if changed_chunks:
        changed_files = set(chunk.chunk.file_path for chunk in changed_chunks)
        click.echo(f"📄 Analyzing {len(changed_files)} changed files")

        # Extract chunks from changed files and their neighbors
        chunker = TreeSitterChunker()
        context_chunks = []

        for changed_file in changed_files:
            file_path = Path(changed_file)
            if file_path.exists():
                try:
                    content = file_path.read_text()
                    file_chunks = chunker.chunk_file(str(file_path), content)
                    context_chunks.extend(file_chunks)
                except Exception:
                    continue

        # Build context
        context_parts = []
        for chunk in context_chunks[:20]:  # Limit context
            context_parts.append(f"File: {chunk.file_path}")
            context_parts.append(f"Type: {chunk.chunk_type}")
            if chunk.name:
                context_parts.append(f"Name: {chunk.name}")
            context_parts.append(f"Code:\n{chunk.content}")
            context_parts.append("-" * 40)

        context = "\n".join(context_parts)
    else:
        context = "No code context available."

    # Generate review
    async with OpenRouterClient(api_key=config.openrouter_api_key) as client:
        try:
            review_prompt = f"""Review this code change:

{diff_content}

Code context from changed files:
{context}

Provide a thorough code review focusing on:
1. Potential bugs or issues
2. Code quality improvements
3. Best practices  
4. Security considerations
5. Performance implications

Format your response with clear sections."""

            click.echo("🤖 Generating review...")
            review = await client.complete([{"role": "user", "content": review_prompt}])

            # Display review
            click.echo("\n" + "=" * 60)
            click.echo("📋 QUICK CODE REVIEW")
            click.echo("=" * 60)
            click.echo(review)
            click.echo("=" * 60)

        except Exception as e:
            click.echo(f"❌ Error during review: {e}")


if __name__ == "__main__":
    cli()
