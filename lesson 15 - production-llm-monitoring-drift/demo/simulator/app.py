import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

registry = CollectorRegistry()

requests_total = Counter(
    "llm_requests_total", "Total LLM requests", ["model", "intent"], registry=registry
)
refusals_total = Counter(
    "llm_refusals_total", "Refused LLM responses", ["model", "intent"], registry=registry
)
cost_total = Counter(
    "llm_cost_usd_total", "Accumulated USD cost", ["model"], registry=registry
)
tokens_total = Counter(
    "llm_tokens_total", "Tokens served", ["model", "kind"], registry=registry
)

duration = Histogram(
    "llm_request_duration_seconds",
    "End-to-end LLM call duration",
    ["model"],
    buckets=(0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0),
    registry=registry,
)

judge_score = Gauge(
    "llm_judge_score",
    "LLM-as-a-Judge faithfulness (0..1), last sampled value",
    ["model", "intent"],
    registry=registry,
)
judge_relevancy = Gauge(
    "llm_judge_relevancy",
    "Answer relevancy (0..1), last sampled value",
    ["model", "intent"],
    registry=registry,
)
judge_context_precision = Gauge(
    "llm_judge_context_precision",
    "Context precision (0..1), last sampled value",
    ["model", "intent"],
    registry=registry,
)
judge_samples_total = Counter(
    "llm_judge_samples_total",
    "Total number of judge evaluations performed",
    ["model", "intent", "verdict"],
    registry=registry,
)
golden_coverage = Gauge(
    "llm_golden_dataset_coverage",
    "Share of incoming intents that exist in golden dataset (0..1)",
    registry=registry,
)
drift_phase = Gauge(
    "llm_drift_phase",
    "Current drift phase: 0=baseline, 1=incident, 2=recovered",
    registry=registry,
)
model_version_info = Gauge(
    "llm_model_version_info",
    "Active model version (label only, value=1)",
    ["model", "version"],
    registry=registry,
)


SCENARIO = os.environ.get("SCENARIO", "model_drift")
RPS = float(os.environ.get("RPS", "5"))
DRIFT_START_SEC = float(os.environ.get("DRIFT_START_SEC", "120"))
DRIFT_DURATION_SEC = float(os.environ.get("DRIFT_DURATION_SEC", "180"))

INTENTS = ["pricing", "refund", "feature_q", "bug_report", "smalltalk"]
MODEL = "gpt-4o"
VERSION_STABLE = "2024-05-13"
VERSION_DRIFTED = "2024-08-06"


class Phase:
    BASELINE = 0
    INCIDENT = 1
    RECOVERED = 2


def current_phase(elapsed: float) -> int:
    if elapsed < DRIFT_START_SEC:
        return Phase.BASELINE
    if elapsed < DRIFT_START_SEC + DRIFT_DURATION_SEC:
        return Phase.INCIDENT
    return Phase.RECOVERED


def sample_one(phase: int) -> None:
    intent = random.choice(INTENTS)

    if phase == Phase.BASELINE:
        latency = random.gauss(0.55, 0.12)
        faithfulness = clamp(random.gauss(0.91, 0.04))
        relevancy = clamp(random.gauss(0.93, 0.03))
        ctx_precision = clamp(random.gauss(0.88, 0.05))
        refusal_p = 0.02
        cost_per_req = random.gauss(0.0012, 0.0002)
        version = VERSION_STABLE
    elif phase == Phase.INCIDENT:
        latency = random.gauss(0.58, 0.15)
        faithfulness = clamp(random.gauss(0.58, 0.09))
        relevancy = clamp(random.gauss(0.74, 0.07))
        ctx_precision = clamp(random.gauss(0.71, 0.08))
        refusal_p = 0.22
        cost_per_req = random.gauss(0.0034, 0.0004)
        version = VERSION_DRIFTED
    else:
        latency = random.gauss(0.56, 0.12)
        faithfulness = clamp(random.gauss(0.88, 0.04))
        relevancy = clamp(random.gauss(0.92, 0.03))
        ctx_precision = clamp(random.gauss(0.86, 0.05))
        refusal_p = 0.03
        cost_per_req = random.gauss(0.0015, 0.0002)
        version = VERSION_DRIFTED

    latency = max(0.05, latency)
    cost_per_req = max(0.0001, cost_per_req)

    model_version_info.labels(model=MODEL, version=version).set(1)

    requests_total.labels(model=MODEL, intent=intent).inc()
    duration.labels(model=MODEL).observe(latency)
    tokens_total.labels(model=MODEL, kind="prompt").inc(random.randint(180, 320))
    tokens_total.labels(model=MODEL, kind="completion").inc(random.randint(60, 220))
    cost_total.labels(model=MODEL).inc(cost_per_req)

    if random.random() < refusal_p:
        refusals_total.labels(model=MODEL, intent=intent).inc()

    if random.random() < 0.4:
        judge_score.labels(model=MODEL, intent=intent).set(faithfulness)
        judge_relevancy.labels(model=MODEL, intent=intent).set(relevancy)
        judge_context_precision.labels(model=MODEL, intent=intent).set(ctx_precision)
        verdict = "pass" if faithfulness >= 0.7 else "fail"
        judge_samples_total.labels(model=MODEL, intent=intent, verdict=verdict).inc()

    golden_coverage.set(0.92 if phase != Phase.INCIDENT else 0.71)


def clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def traffic_loop() -> None:
    start = time.time()
    interval = 1.0 / RPS
    while True:
        elapsed = time.time() - start
        phase = current_phase(elapsed)
        drift_phase.set(phase)
        sample_one(phase)
        time.sleep(interval)


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            output = generate_latest(registry)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)
        elif self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def main() -> None:
    threading.Thread(target=traffic_loop, daemon=True).start()
    server = HTTPServer(("0.0.0.0", 8000), MetricsHandler)
    print(
        f"[simulator] scenario={SCENARIO} rps={RPS} drift_start={DRIFT_START_SEC}s "
        f"drift_duration={DRIFT_DURATION_SEC}s — serving /metrics on :8000",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
