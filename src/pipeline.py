"""Pipeline entrypoints and stage orchestration."""

from __future__ import annotations

import json
import logging
import time
import uuid

from .config import load_settings

LOGGER = logging.getLogger("research.pipeline")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")



def _log_event(*, pipeline_run_id: str, stage: str, event: str, elapsed_s: float | None = None) -> None:
    payload: dict[str, object] = {
        "pipeline_run_id": pipeline_run_id,
        "stage": stage,
        "event": event,
    }
    if elapsed_s is not None:
        payload["elapsed_s"] = round(elapsed_s, 3)
    LOGGER.info(json.dumps(payload, sort_keys=True))



def _run_stage(stage: str, pipeline_run_id: str) -> None:
    start = time.perf_counter()
    _log_event(pipeline_run_id=pipeline_run_id, stage=stage, event="start")

    # Placeholder for stage-specific implementation.
    _ = load_settings()

    elapsed = time.perf_counter() - start
    _log_event(pipeline_run_id=pipeline_run_id, stage=stage, event="complete", elapsed_s=elapsed)



def run_ingestion(*, pipeline_run_id: str | None = None) -> str:
    pipeline_run_id = pipeline_run_id or str(uuid.uuid4())
    _run_stage("ingestion", pipeline_run_id)
    return pipeline_run_id



def run_embedding(*, pipeline_run_id: str | None = None) -> str:
    pipeline_run_id = pipeline_run_id or str(uuid.uuid4())
    _run_stage("embedding", pipeline_run_id)
    return pipeline_run_id



def run_generation(*, pipeline_run_id: str | None = None) -> str:
    pipeline_run_id = pipeline_run_id or str(uuid.uuid4())
    _run_stage("generation", pipeline_run_id)
    return pipeline_run_id



def run_verification(*, pipeline_run_id: str | None = None) -> str:
    pipeline_run_id = pipeline_run_id or str(uuid.uuid4())
    _run_stage("verification", pipeline_run_id)
    return pipeline_run_id



def run_delivery(*, pipeline_run_id: str | None = None) -> str:
    pipeline_run_id = pipeline_run_id or str(uuid.uuid4())
    _run_stage("delivery", pipeline_run_id)
    return pipeline_run_id



def run_all(*, pipeline_run_id: str | None = None) -> str:
    pipeline_run_id = pipeline_run_id or str(uuid.uuid4())
    for stage in ("ingestion", "embedding", "generation", "verification", "delivery"):
        _run_stage(stage, pipeline_run_id)
    return pipeline_run_id
