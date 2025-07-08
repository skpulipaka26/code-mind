# Turbo-Review Observability Stack

This directory contains the complete observability stack for monitoring Turbo-Review performance, costs, and usage patterns.

## Components

- **OpenTelemetry Collector**: Receives traces, metrics, and logs from the application
- **Jaeger**: Distributed tracing visualization 
- **Prometheus**: Metrics storage and querying
- **Grafana**: Dashboards and visualization
- **Loki**: Log aggregation
- **Promtail**: Log collection

## Quick Start

1. **Start the observability stack:**
   ```bash
   cd docker
   docker-compose up -d
   ```

2. **Access the interfaces:**
   - Grafana: http://localhost:3000 (admin/admin)
   - Jaeger UI: http://localhost:16686
   - Prometheus: http://localhost:9090

3. **Run turbo-review with telemetry:**
   ```bash
   # Set environment variables for telemetry
   export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
   export OTEL_SERVICE_NAME=turbo-review
   
   # Run commands - telemetry will be automatically collected
   turbo-review index /path/to/repo
   turbo-review review diff.patch
   ```

## Dashboards

The Grafana instance comes pre-configured with:

- **Turbo-Review Overview**: Key metrics including:
  - Review duration (p95, p50)
  - API request rates
  - Total costs per hour
  - Indexed chunk counts
  - Operation latency trends
  - Error rates

## Metrics Collected

### Performance Metrics
- `turbo_review_duration_seconds`: End-to-end review generation time
- `turbo_embedding_duration_seconds`: Embedding generation latency  
- `turbo_retrieval_duration_seconds`: Vector search performance

### Usage Metrics
- `turbo_api_requests_total`: API request counts by model and operation
- `turbo_chunks_indexed`: Number of code chunks in the vector database

### Cost Metrics
- `turbo_cost_total`: Estimated API costs in USD

## Traces

Distributed traces show the complete request flow:
- Repository indexing operations
- Diff processing and review generation
- Vector search and reranking
- API calls to OpenRouter

## Configuration

### Environment Variables
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OTLP collector endpoint (default: http://localhost:4317)
- `OTEL_SERVICE_NAME`: Service name for telemetry (default: turbo-review)
- `OTEL_SERVICE_VERSION`: Service version (default: 0.1.0)

### Customization
- Edit `otel-collector.yml` to modify telemetry pipeline
- Update `prometheus.yml` to add new scrape targets
- Modify Grafana dashboards in `grafana/dashboards/`

## Troubleshooting

1. **No metrics appearing:**
   - Check that the OTEL collector is running: `docker-compose ps`
   - Verify OTLP endpoint is accessible: `curl http://localhost:4317`

2. **High cardinality warnings:**
   - Review metric labels in the telemetry configuration
   - Consider sampling traces in production

3. **Storage issues:**
   - Monitor disk usage for Prometheus and Grafana volumes
   - Configure retention policies in `prometheus.yml`