"""Content-free native SDK turn and tool spans."""
from contextlib import contextmanager
import os

from opentelemetry import propagate, trace


def configure():
    if os.getenv("AGENTTEAMS_OTEL_ENABLED", "").lower() not in {"true", "1"}:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    provider = TracerProvider(resource=Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "agentteams-claude-code"),
        "agentteams.runtime": "claudecode", "agentteams.worker.name": os.getenv("AGENTTEAMS_WORKER_NAME", "")}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


@contextmanager
def turn_span(role, task, model):
    packet = task.get("coordination") or {}
    identity = task.get("identity") or {}
    ids = [s["eventId"] for s in task.get("sources") or []]
    if not ids and task.get("sourceEvent"):
        ids = [task["sourceEvent"]]
    fields = {"agentteams.harness": "claudecode", "agentteams.role": role, "gen_ai.request.model": model,
              "agentteams.input.event_ids": ids, "agentteams.event.id": task.get("sourceEvent"),
              "agentteams.room.id": task.get("room"), "agentteams.task.id": identity.get("task_id") or packet.get("task_id"),
              "agentteams.coordination.id": packet.get("id"), "agentteams.coordination.kind": packet.get("kind"),
              "agentteams.execution.generation": identity.get("generation")}
    with trace.get_tracer("agentteams.claude-code").start_as_current_span("claude-code.turn",
            context=propagate.extract(task.get("carrier") or {}), attributes={k: v for k, v in fields.items() if v},
            record_exception=False, set_status_on_exception=False) as span:
        yield span
