#!/bin/bash

echo "🚀 Testing Turbo-Review Observability Stack"
echo "=========================================="

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "✅ Docker is running"

# Start the stack
echo "🔧 Starting observability stack..."
docker-compose up -d

echo "⏳ Waiting for services to start..."
sleep 10

# Check service health
echo "🔍 Checking service health..."

services=("grafana:3000" "jaeger:16686" "prometheus:9090" "otel-collector:8888")
all_healthy=true

for service in "${services[@]}"; do
    name=$(echo $service | cut -d: -f1)
    port=$(echo $service | cut -d: -f2)
    
    if curl -s "http://localhost:$port" >/dev/null 2>&1; then
        echo "✅ $name is healthy (port $port)"
    else
        echo "❌ $name is not responding (port $port)"
        all_healthy=false
    fi
done

if $all_healthy; then
    echo ""
    echo "🎉 All services are healthy!"
    echo ""
    echo "Access URLs:"
    echo "- Grafana: http://localhost:3000 (admin/admin)"
    echo "- Jaeger: http://localhost:16686"
    echo "- Prometheus: http://localhost:9090"
    echo "- OTEL Collector: http://localhost:8888"
    echo ""
    echo "To test with turbo-review:"
    echo "export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317"
    echo "turbo-review --help"
else
    echo ""
    echo "❌ Some services are not healthy. Check the logs:"
    echo "docker-compose logs"
fi

echo ""
echo "To stop the stack: docker-compose down"