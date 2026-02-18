from src.pipeline import _persist_stage_cost_metrics


class _Cursor:
    def __init__(self, scripted_fetches):
        self._scripted_fetches = list(scripted_fetches)
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        if not self._scripted_fetches:
            return None
        return self._scripted_fetches.pop(0)


class _Connection:
    def __init__(self, scripted_fetches):
        self.cursor_obj = _Cursor(scripted_fetches)

    def cursor(self):
        return self.cursor_obj


def test_persist_stage_cost_metrics_updates_without_metadata_column() -> None:
    connection = _Connection(
        [
            (False, True),  # has_metadata, has_cost_estimate_json
            (11, {"stages": {}}),  # existing pipeline_runs row
        ]
    )

    _persist_stage_cost_metrics(
        connection,
        pipeline_run_id="run-123",
        stage="ingestion",
        metrics={"token_count": 0, "estimated_cost_usd": 0.0},
    )

    select_query, _ = connection.cursor_obj.executed[1]
    assert "SELECT id, cost_estimate_json FROM pipeline_runs" in select_query

    update_query, update_params = connection.cursor_obj.executed[-1]
    assert "SET cost_estimate_json = %s::jsonb, status = %s" in update_query
    assert "metadata = %s::jsonb" not in update_query
    assert update_params is not None
    assert update_params[-1] == 11


def test_persist_stage_cost_metrics_inserts_without_metadata_or_cost_columns() -> None:
    connection = _Connection(
        [
            (False, False),  # has_metadata, has_cost_estimate_json
            None,  # no existing pipeline_runs row
            (42,),  # RETURNING id for inserted row
        ]
    )

    _persist_stage_cost_metrics(
        connection,
        pipeline_run_id="run-legacy",
        stage="ingestion",
        metrics={"token_count": 0, "estimated_cost_usd": 0.0},
    )

    insert_query, _ = connection.cursor_obj.executed[2]
    assert "INSERT INTO pipeline_runs (run_name, status)" in insert_query

    update_query, _ = connection.cursor_obj.executed[-1]
    assert "SET status = %s" in update_query
    assert "metadata" not in update_query
    assert "cost_estimate_json" not in update_query
