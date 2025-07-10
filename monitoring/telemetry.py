"""OpenTelemetry setup and instrumentation for CodeMind."""

import os
from typing import Optional, Dict, Any
from contextlib import contextmanager

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from utils.logging import get_logger


class TelemetryManager:
    """Manages OpenTelemetry setup for CodeMind."""

    def __init__(self):
        self.tracer: Optional[trace.Tracer] = None
        self.meter: Optional[metrics.Meter] = None
        self.logger = get_logger(__name__)
        self._initialized = False

        # Metrics
        self.review_duration_histogram: Optional[metrics.Histogram] = None
        self.embedding_duration_histogram: Optional[metrics.Histogram] = None
        self.retrieval_duration_histogram: Optional[metrics.Histogram] = None
        self.api_request_counter: Optional[metrics.Counter] = None
        self.cost_counter: Optional[metrics.Counter] = None
        self.chunk_count_gauge: Optional[metrics.UpDownCounter] = None

    def setup(
        self,
        service_name: str = "codemind",
        service_version: str = "0.1.0",
        otlp_endpoint: str = "http://localhost:4317",
    ):
        """Initialize OpenTelemetry with OTLP exporters."""
        if self._initialized:
            return

        # Create resource
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
            }
        )

        # Setup tracing
        trace_provider = TracerProvider(resource=resource)
        trace_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        span_processor = BatchSpanProcessor(trace_exporter)
        trace_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(trace_provider)

        # Setup metrics
        metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter, export_interval_millis=5000
        )
        metric_provider = MeterProvider(
            resource=resource, metric_readers=[metric_reader]
        )
        metrics.set_meter_provider(metric_provider)

        # Get tracer and meter
        self.tracer = trace.get_tracer(__name__)
        self.meter = metrics.get_meter(__name__)

        # Setup auto-instrumentation
        RequestsInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()

        # Initialize metrics
        self._setup_metrics()

        self._initialized = True
        self.logger.info(f"OpenTelemetry initialized for {service_name}")

    def _setup_metrics(self):
        """Setup custom metrics for codemind."""
        if not self.meter:
            return

        self.review_duration_histogram = self.meter.create_histogram(
            name="codemind_duration_seconds",
            description="Time taken to generate code reviews",
            unit="s",
        )

        self.embedding_duration_histogram = self.meter.create_histogram(
            name="codemind_embedding_duration_seconds",
            description="Time taken to generate embeddings",
            unit="s",
        )

        self.retrieval_duration_histogram = self.meter.create_histogram(
            name="codemind_retrieval_duration_seconds",
            description="Time taken for vector retrieval",
            unit="s",
        )

        self.api_request_counter = self.meter.create_counter(
            name="codemind_api_requests_total",
            description="Total number of API requests",
        )

        self.cost_counter = self.meter.create_counter(
            name="codemind_cost_total",
            description="Total cost of API requests",
            unit="USD",
        )

        self.chunk_count_gauge = self.meter.create_up_down_counter(
            name="codemind_chunks_indexed",
            description="Number of code chunks indexed",
        )

    @contextmanager
    def trace_operation(
        self, operation_name: str, attributes: Optional[Dict[str, Any]] = None
    ):
        """Context manager for tracing operations."""
        if not self.tracer:
            yield None
            return

        with self.tracer.start_as_current_span(operation_name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            yield span

    def record_review_duration(
        self, duration: float, attributes: Optional[Dict[str, Any]] = None
    ):
        """Record code review duration."""
        if self.review_duration_histogram:
            self.review_duration_histogram.record(duration, attributes or {})

    def record_embedding_duration(
        self, duration: float, attributes: Optional[Dict[str, Any]] = None
    ):
        """Record embedding generation duration."""
        if self.embedding_duration_histogram:
            self.embedding_duration_histogram.record(duration, attributes or {})

    def record_retrieval_duration(
        self, duration: float, attributes: Optional[Dict[str, Any]] = None
    ):
        """Record vector retrieval duration."""
        if self.retrieval_duration_histogram:
            self.retrieval_duration_histogram.record(duration, attributes or {})

    def increment_api_requests(self, attributes: Optional[Dict[str, Any]] = None):
        """Increment API request counter."""
        if self.api_request_counter:
            self.api_request_counter.add(1, attributes or {})

    def record_cost(self, cost: float, attributes: Optional[Dict[str, Any]] = None):
        """Record API cost."""
        if self.cost_counter:
            self.cost_counter.add(cost, attributes or {})

    def update_chunk_count(
        self, count: int, attributes: Optional[Dict[str, Any]] = None
    ):
        """Update indexed chunk count."""
        if self.chunk_count_gauge:
            self.chunk_count_gauge.add(count, attributes or {})


# Global telemetry manager instance
telemetry = TelemetryManager()


def get_telemetry() -> TelemetryManager:
    """Get the global telemetry manager."""
    return telemetry


def setup_telemetry():
    """Setup telemetry from environment variables."""
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    service_name = os.getenv("OTEL_SERVICE_NAME", "codemind")
    service_version = os.getenv("OTEL_SERVICE_VERSION", "0.1.0")

    telemetry.setup(
        service_name=service_name,
        service_version=service_version,
        otlp_endpoint=otlp_endpoint,
    )
