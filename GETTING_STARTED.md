# CodeMind - Getting Started Guide

A comprehensive guide to set up, use, and query the CodeMind AI-powered codebase intelligence platform.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Core Features](#core-features)
- [Database Queries](#database-queries)
- [API Usage](#api-usage)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.10-3.12
- Docker and Docker Compose
- uv (Python package manager)
- Git
- At least 8GB RAM (for running all services)

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/skpulipaka26/turbo-review.git
cd turbo-review

# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync
uv sync --extra dev  # For development tools
```

### 2. Configure API Keys (Optional)

Create a `.env` file for API keys:

```bash
# For OpenRouter/OpenAI models (optional - uses local models by default)
OPENROUTER_API_KEY=your_key_here
```

### 3. Start Services

```bash
# Start all required services (databases, monitoring)
docker-compose up -d

# Wait ~30 seconds for services to initialize
sleep 30

# Verify services are running
docker ps --format "table {{.Names}}\t{{.Status}}"

# Check database health
uv run python main.py health
```

Expected output:
```
=== Database Health Check ===
Vector DB (Qdrant): ✅
Graph DB (Neo4j): ✅
Total repositories: 0
All databases are healthy! 🎉
```

### 4. Index Your First Repository

```bash
# Index a local repository
uv run python main.py index /path/to/your/repo

# Index a remote repository (will clone it first)
uv run python main.py index https://github.com/owner/repo.git
```

### 5. Start the API Server

```bash
# Start the API server
uv run python -m api.main

# API will be available at:
# - http://localhost:8000 (API root)
# - http://localhost:8000/docs (Swagger UI)
```

## Core Features

### 1. Command Line Interface

```bash
# Index a repository
uv run python main.py index <repo_path>

# Review a code diff
uv run python main.py review <diff_file.patch>

# Check system health
uv run python main.py health
```

### 2. API Endpoints

#### Repository Management
```bash
# List all indexed repositories
curl http://localhost:8000/api/v1/repositories/

# Index a new repository via API
curl -X POST http://localhost:8000/api/v1/repositories/index \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/owner/repo.git"}'
```

#### Code Review
```bash
# Submit a diff for review
curl -X POST http://localhost:8000/api/v1/reviews/ \
  -H "Content-Type: application/json" \
  -d '{
    "diff_content": "diff --git a/file.py...",
    "repo_url": "git@github.com:owner/repo.git"
  }'

# Quick review without context
curl -X POST http://localhost:8000/api/v1/reviews/quick \
  -H "Content-Type: application/json" \
  -d '{"diff_content": "diff --git a/file.py..."}'
```

#### Codebase Chat
```bash
# Ask questions about the codebase
curl -X POST http://localhost:8000/api/v1/conversations/ \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How does the authentication system work?",
    "repo_url": "git@github.com:owner/repo.git",
    "max_results": 5
  }'

# Search for code
curl -X POST http://localhost:8000/api/v1/conversations/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "database connection handling",
    "max_results": 10
  }'
```

## Database Queries

### Using the Query Script

The project includes a `query_db.py` script for database operations:

```bash
# List all indexed repositories
uv run python query_db.py list-repos

# List chunks for a specific repository
uv run python query_db.py list-chunks <repo_name>

# Search across all indexed code
uv run python query_db.py search "your search query"

# Show details of a specific chunk
uv run python query_db.py show-chunk <chunk_id>

# Clear all data (WARNING: destructive)
uv run python query_db.py clear-all

# Clear only vector database
uv run python query_db.py clear-vector

# Clear only graph database
uv run python query_db.py clear-graph
```

#### Examples:
```bash
# Search for authentication code
uv run python query_db.py search "authentication login user"

# List chunks from a specific repo
uv run python query_db.py list-chunks turbo-review

# Show a specific chunk's details
uv run python query_db.py show-chunk chunk_12345
```

### Direct Database Access

#### Qdrant (Vector Database) - Port 6333

**Web Dashboard:**
```bash
# Open Qdrant dashboard in browser
open http://localhost:6333/dashboard
```

**REST API Queries:**
```bash
# List all collections
curl http://localhost:6333/collections

# Get collection details
curl http://localhost:6333/collections/repo_git_github_com_owner_repo

# Get collection statistics
curl http://localhost:6333/collections/repo_git_github_com_owner_repo/points/count
```

**Python Client:**
```python
from qdrant_client import QdrantClient
import numpy as np

# Connect to Qdrant
client = QdrantClient(host="localhost", port=6333)

# List all collections
collections = client.get_collections()
print(f"Collections: {collections}")

# Get points from a collection
collection_name = "repo_git_github_com_owner_repo"
points = client.scroll(
    collection_name=collection_name,
    limit=10
)

# Search with a random vector (normally you'd use actual embeddings)
results = client.search(
    collection_name=collection_name,
    query_vector=np.random.rand(768).tolist(),  # 768-dim vector
    limit=5
)

for result in results:
    print(f"Score: {result.score}, ID: {result.id}")
    print(f"Payload: {result.payload}")
```

#### Neo4j (Graph Database) - Port 7474/7687

**Neo4j Browser:**
```bash
# Open Neo4j browser interface
open http://localhost:7474

# Login credentials:
# Username: neo4j
# Password: turbo-review-password
```

**Cypher Shell Queries:**
```bash
# Connect to Neo4j via command line
docker exec -it turbo-review-neo4j cypher-shell \
  -u neo4j -p turbo-review-password

# Then run Cypher queries:

# Show database statistics
MATCH (n) RETURN labels(n) as NodeType, count(*) as Count;

# Find all functions
MATCH (f:Function) 
RETURN f.name, f.file_path 
LIMIT 20;

# Find all classes and their methods
MATCH (c:Class)-[:CONTAINS]->(m:Function)
RETURN c.name as Class, collect(m.name) as Methods
LIMIT 10;

# Find function call relationships
MATCH (f1:Function)-[:CALLS]->(f2:Function)
RETURN f1.name as Caller, f2.name as Called
LIMIT 20;

# Find import dependencies
MATCH (f1:CodeChunk)-[:IMPORTS]->(f2:CodeChunk)
RETURN f1.file_path, f2.file_path
LIMIT 20;

# Find most connected functions (hub functions)
MATCH (f:Function)
WITH f, size((f)-[:CALLS]->()) as outgoing, 
     size((f)<-[:CALLS]-()) as incoming
WHERE outgoing > 0 OR incoming > 0
RETURN f.name, f.file_path, outgoing, incoming, 
       outgoing + incoming as total_connections
ORDER BY total_connections DESC
LIMIT 10;

# Find code communities
MATCH (c:Community)
RETURN c.id, c.summary, c.chunk_count
LIMIT 10;
```

**Python Client:**
```python
from neo4j import GraphDatabase

class Neo4jConnection:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            "bolt://localhost:7687",
            auth=("neo4j", "turbo-review-password")
        )
    
    def close(self):
        self.driver.close()
    
    def get_all_functions(self):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (f:Function)
                RETURN f.name as name, f.file_path as path
                LIMIT 50
            """)
            return [dict(record) for record in result]
    
    def find_dependencies(self, function_name):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (f:Function {name: $name})-[:CALLS]->(dep:Function)
                RETURN dep.name as dependency, dep.file_path as path
            """, name=function_name)
            return [dict(record) for record in result]
    
    def get_call_graph(self):
        with self.driver.session() as session:
            result = session.run("""
                MATCH (f1:Function)-[:CALLS]->(f2:Function)
                RETURN f1.name as source, f2.name as target
                LIMIT 100
            """)
            return [dict(record) for record in result]

# Usage example
conn = Neo4jConnection()

# Get all functions
functions = conn.get_all_functions()
for func in functions[:10]:
    print(f"Function: {func['name']} in {func['path']}")

# Find dependencies of a specific function
deps = conn.find_dependencies("index_repository")
print(f"\nDependencies of index_repository:")
for dep in deps:
    print(f"  - {dep['dependency']} ({dep['path']})")

conn.close()
```

## Service URLs

When all services are running, you can access:

- **API Server**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Qdrant Dashboard**: http://localhost:6333/dashboard
- **Neo4j Browser**: http://localhost:7474
- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Jaeger UI**: http://localhost:16686

## Common Operations

### Re-index a Repository
```bash
# First, clear the existing data for that repo
uv run python query_db.py clear-all  # Or be more selective

# Then re-index
uv run python main.py index /path/to/repo
```

### Review Your Own Code Changes
```bash
# Generate a diff file
git diff > my_changes.patch

# Get AI review
uv run python main.py review my_changes.patch
```

### Batch Index Multiple Repositories
```bash
# Create a script to index multiple repos
for repo in repo1 repo2 repo3; do
    uv run python main.py index /path/to/$repo
    sleep 5  # Give the system a break between large indexes
done
```

## Troubleshooting

### Services Won't Start
```bash
# Check Docker is running
docker version

# Check for port conflicts
lsof -i :6333  # Qdrant
lsof -i :7474  # Neo4j HTTP
lsof -i :7687  # Neo4j Bolt
lsof -i :8000  # API server

# Restart services
docker-compose down
docker-compose up -d

# Check logs
docker-compose logs qdrant
docker-compose logs neo4j
```

### Database Connection Issues
```bash
# Check if services are healthy
uv run python main.py health

# Manually test connections
curl http://localhost:6333/  # Should return Qdrant info
curl http://localhost:7474/  # Should redirect to Neo4j browser

# Reset databases (WARNING: deletes all data)
docker-compose down -v
docker-compose up -d
```

### Indexing Issues
```bash
# Check available disk space
df -h

# Monitor indexing progress
tail -f review_output.log

# For large repositories, increase timeout
export INDEX_TIMEOUT=3600  # 1 hour
```

### API Server Issues
```bash
# Check if port 8000 is available
lsof -i :8000

# Run with debug logging
export LOG_LEVEL=DEBUG
uv run python -m api.main

# Check API health
curl http://localhost:8000/health
```

## Performance Tips

1. **For Large Codebases**: Index incrementally by subdirectory
2. **Memory Usage**: Monitor with `docker stats`
3. **Disk Space**: Ensure at least 10GB free for databases
4. **Concurrent Indexing**: Avoid indexing multiple large repos simultaneously
5. **Query Optimization**: Use specific repo_url filters in API calls

## Next Steps

1. Index your codebase
2. Try the chat interface to ask questions about your code
3. Submit a PR for AI-powered code review
4. Explore the knowledge graph in Neo4j Browser
5. Build custom queries for your specific needs

For more details, see the main [README.md](README.md) or check the API documentation at http://localhost:8000/docs when the server is running.