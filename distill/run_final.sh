#!/usr/bin/env bash
# Full teacher-dataset run: exactly 1,000 questions -> Claude teacher answers -> quality gates -> leakage-safe split.
# Every stage is resumable: re-running this script continues where it stopped. Run from the repository root
# only after data/distill/final_readiness_report.md records a GO decision.
set -euo pipefail
cd "$(dirname "$0")/.."

RUN=final
EXCLUDE=(
  data/distill/pilot/questions.jsonl                     # original pilot (diagnosed; not reused)
  data/distill/retrieval_eval/fresh_v1/questions.jsonl   # retrieval development set
  data/distill/retrieval_eval/heldout_v2/questions.jsonl # held-out retrieval evaluation set
  data/distill/heldout_v2_gen/questions.jsonl            # held-out generated questions (incl. any dropped for overlap)
  data/distill/pilot_v2/questions.jsonl                  # validation pilot
  data/distill/smoke_v2/questions.jsonl                  # smoke test
)

echo "[$(date -u +%FT%TZ)] questions"
.venv/bin/python distill/build_questions.py --run "$RUN" --target 1000 --workers 8 --exclude-seeds "${EXCLUDE[@]}"

echo "[$(date -u +%FT%TZ)] teacher answers"
.venv/bin/python distill/generate_teacher.py --run "$RUN" --workers 8
# One pass over any pipeline errors left after in-run retries.
.venv/bin/python distill/generate_teacher.py --run "$RUN" --workers 4 --retry-errors

echo "[$(date -u +%FT%TZ)] split and report"
.venv/bin/python distill/split_and_report.py --run "$RUN"
echo "[$(date -u +%FT%TZ)] done"
