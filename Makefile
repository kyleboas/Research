PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)

.PHONY: help test-detect eval-detect eval-report optimize-ingest-policy optimize-report-policy autoresearch-daily benchmark-report dashboard step-ingest step-backfill step-detect step-rescore step-report

help:
	@printf "Targets:\n"
	@printf "  make test-detect   Run detect-related unit tests\n"
	@printf "  make eval-detect   Run offline detect-policy evaluation\n"
	@printf "  make eval-report   Run offline report-quality evaluation\n"
	@printf "  make optimize-ingest-policy Tune ingest policy with no-LLM heuristics\n"
	@printf "  make benchmark-report Run report-policy benchmark on recent reports\n"
	@printf "  make optimize-report-policy Search/apply the best report policy on recent reports\n"
	@printf "  make autoresearch-daily Run the full no-LLM autoresearch pipeline\n"
	@printf "  make dashboard     Start the local dashboard server\n"
	@printf "  make step-ingest   Run ingest\n"
	@printf "  make step-backfill Run backfill\n"
	@printf "  make step-detect   Run detect\n"
	@printf "  make step-rescore  Run rescore\n"
	@printf "  make step-report   Run report\n"

test-detect:
	$(PYTHON) -m unittest \
		tests.test_pipeline_helpers \
		tests.test_novelty_scoring \
		tests.test_detect_policy \
		tests.test_detect_evaluator

eval-detect:
	$(PYTHON) autoresearch/detect/eval_detect.py

eval-report:
	$(PYTHON) autoresearch/report/eval_report.py --refresh-auto

optimize-ingest-policy:
	$(PYTHON) autoresearch/ingest/optimize_ingest_policy.py --apply

benchmark-report:
	$(PYTHON) autoresearch/report/benchmark_report.py --refresh-auto --limit 3

optimize-report-policy:
	$(PYTHON) autoresearch/report/optimize_report_policy.py --refresh-auto --limit 2

autoresearch-daily:
	$(PYTHON) autoresearch/pipeline.py

dashboard:
	$(PYTHON) server.py

step-ingest:
	$(PYTHON) main.py --step ingest

step-backfill:
	$(PYTHON) main.py --step backfill

step-detect:
	$(PYTHON) main.py --step detect

step-rescore:
	$(PYTHON) main.py --step rescore

step-report:
	$(PYTHON) main.py --step report
