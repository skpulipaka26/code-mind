# Turbo-Review

AI-powered code review system using Qwen3 models for semantic code analysis and automated review generation.

## Overview

Turbo-Review analyzes code repositories using Tree-sitter parsing, vector embeddings, and large language models to provide intelligent code reviews. The system can index entire repositories, process git diffs, and generate contextual feedback on code changes.

## Features

- **Semantic Code Analysis**: Tree-sitter based parsing for Python, JavaScript, and TypeScript
- **Vector Search**: FAISS-powered similarity search for relevant code context
- **AI-Powered Reviews**: Qwen3 models via OpenRouter for intelligent code analysis
- **Multi-Language Support**: Python, JavaScript, TypeScript, JSX, TSX files
- **GitHub Integration**: Automated pull request reviews
- **Observability**: Complete OpenTelemetry instrumentation with Grafana dashboards
- **CLI Interface**: Simple command-line tools for local development

## Installation

### Prerequisites

- Python 3.13+
- OpenRouter API key
- Docker and Docker Compose (for monitoring stack)

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd turbo-review
```

2. Install dependencies:
```bash
pip install uv
uv sync
```

3. Configure environment variables:
```bash
# Required
export OPENROUTER_API_KEY="your-api-key-here"

# Optional (for monitoring)
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
export OTEL_SERVICE_NAME="turbo-review"
```

## Usage

### Basic Commands

The CLI provides three main commands:

1. **Index a repository**:
```bash
turbo-review index /path/to/repository
```

2. **Review a diff file**:
```bash
turbo-review review changes.diff --index myrepo
```

3. **Quick review without indexing**:
```bash
turbo-review quick /path/to/repository changes.diff
```

### Detailed Workflow

#### 1. Repository Indexing

Index your codebase to enable context-aware reviews:

```bash
# Index with default name 'index'
turbo-review index ./my-project

# Index with custom name
turbo-review index ./my-project --output my-project-index
```

This command:
- Parses all Python, JavaScript, and TypeScript files
- Extracts functions, classes, and imports using Tree-sitter
- Generates embeddings using Qwen3-Embedding-0.6B
- Stores vectors in a local FAISS database

#### 2. Reviewing Changes

Create a diff file and review it:

```bash
# Generate a diff file
git diff > changes.diff

# Review using indexed repository
turbo-review review changes.diff --index my-project-index

# Review with repository context
turbo-review review changes.diff --repo ./my-project
```

The review process:
- Parses the unified diff format
- Identifies changed code chunks
- Searches for relevant context using vector similarity
- Reranks results using Qwen3 models
- Generates a comprehensive code review

#### 3. Quick Reviews

For immediate feedback without pre-indexing:

```bash
turbo-review quick ./my-project changes.diff
```

This mode:
- Analyzes only the changed files
- Provides contextual review without vector search
- Faster execution but less comprehensive context

### Configuration

Create a configuration file for persistent settings:

```yaml
# config.yaml
openrouter_api_key: "your-api-key"
embedding_model: "qwen/qwen3-embedding-0.6b"
completion_model: "qwen/qwen2.5-coder-7b-instruct"
```

Use with:
```bash
turbo-review --config config.yaml index ./project
```

### Environment Variables

- `OPENROUTER_API_KEY`: Your OpenRouter API key (required)
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OpenTelemetry endpoint for monitoring
- `OTEL_SERVICE_NAME`: Service name for telemetry (default: turbo-review)
- `OTEL_SERVICE_VERSION`: Service version for telemetry

## GitHub Integration

### Setup GitHub App

1. Create a GitHub App with the following permissions:
   - Contents: Read
   - Pull requests: Read & Write
   - Metadata: Read

2. Install the app on your repositories

3. Configure webhook endpoint for pull request events

### Automated Reviews

The system can automatically review pull requests:

```python
from integrations.github import GitHubIntegration

# Initialize with your GitHub app credentials
github = GitHubIntegration(
    app_id="your-app-id",
    private_key="your-private-key",
    webhook_secret="your-webhook-secret"
)

# Process webhook events
github.handle_pull_request_event(webhook_payload)
```

## Monitoring and Observability

### Starting the Monitoring Stack

1. Navigate to the docker directory:
```bash
cd docker
```

2. Start all services:
```bash
docker-compose up -d
```

3. Verify services are running:
```bash
./test-stack.sh
```

### Access Dashboards

- **Grafana**: http://localhost:3000 (admin/admin)
  - Pre-configured dashboards for Turbo-Review metrics
  - Performance monitoring and cost tracking
  - Error rate analysis

- **Jaeger**: http://localhost:16686
  - Distributed tracing for request flows
  - Performance bottleneck identification

- **Prometheus**: http://localhost:9090
  - Raw metrics and alerting
  - Query interface for custom analysis

### Key Metrics

The system automatically tracks:

- **Performance**: Review duration, embedding generation time, vector search latency
- **Usage**: API request counts, processed chunks, repository sizes
- **Costs**: Estimated API costs by model and operation
- **Errors**: Failed requests, parsing errors, API failures

## Architecture

### Core Components

- **TreeSitterChunker**: Extracts semantic code chunks (functions, classes, imports)
- **VectorDatabase**: FAISS-based storage for code embeddings
- **OpenRouterClient**: Interface to Qwen3 models via OpenRouter API
- **DiffProcessor**: Parses git diffs and identifies changed code
- **CodeReranker**: Improves search results using relevance scoring

### Data Flow

1. **Indexing**: Code → Tree-sitter → Chunks → Embeddings → Vector DB
2. **Review**: Diff → Changed chunks → Vector search → Reranking → LLM → Review

### Models Used

- **Qwen3-Embedding-0.6B**: Code embeddings (896 dimensions)
- **Qwen2.5-Coder-7B-Instruct**: Code review generation
- **Qwen3-Reranker**: Result relevance scoring

## Development

### Running Tests

```bash
uv run pytest tests/ -v
```

### Code Structure

```
turbo-review/
├── cli/                    # Command-line interface
├── core/                   # Core functionality (chunking, vector DB)
├── inference/              # AI model interfaces
├── processing/             # Diff processing and reranking
├── integrations/           # GitHub/GitLab integrations
├── monitoring/             # OpenTelemetry instrumentation
├── docker/                 # Observability stack
└── tests/                  # Test suite
```

### Adding New Languages

To support additional programming languages:

1. Install the Tree-sitter parser: `pip install tree-sitter-<language>`
2. Add language detection in `TreeSitterChunker._detect_language()`
3. Implement extraction logic in `TreeSitterChunker._extract_chunks()`

## Troubleshooting

### Common Issues

**No API key configured**:
```bash
export OPENROUTER_API_KEY="your-key-here"
```

**Tree-sitter parsing errors**:
- Ensure language parsers are installed
- Check file encoding (UTF-8 required)
- Verify syntax is valid

**Vector database errors**:
- Check available disk space
- Ensure write permissions in current directory
- Verify FAISS installation

**Monitoring not working**:
- Confirm Docker is running
- Check port availability (3000, 4317, 9090, 16686)
- Verify OTLP endpoint configuration

### Performance Optimization

- **Batch size**: Adjust embedding batch size based on memory
- **Chunk limit**: Limit context chunks for large repositories
- **Sampling**: Enable trace sampling for high-volume usage
- **Caching**: Use persistent vector indices for repeated analysis

## API Costs

Estimated costs per operation:
- Embedding generation: ~$0.00001 per token
- Code review generation: ~$0.00002 per token
- Typical repository indexing: $0.10-1.00
- Typical review generation: $0.01-0.10

Monitor costs in Grafana dashboards or check OpenRouter usage.
