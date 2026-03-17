#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="bitoguard_official_pipeline"
PROJECT_ROOT="/home/a0210/projects/sideProject/bitoguard_project_bundle"
CORE_DIR="${PROJECT_ROOT}/bitoguard_core"
ARTIFACT_DIR="${CORE_DIR}/artifacts"
LOG_DIR="${ARTIFACT_DIR}/logs"
LOG_FILE="${LOG_DIR}/official_pipeline.log"

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "Missing required file: ${path}" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "Missing required directory: ${path}" >&2
    exit 1
  fi
}

echo "[check] validating runtime prerequisites"
command -v tmux >/dev/null 2>&1 || { echo "tmux not found" >&2; exit 1; }
require_dir "${CORE_DIR}"
require_file "${CORE_DIR}/.venv/bin/python"
require_dir "${PROJECT_ROOT}/data/aws_event/clean"
for name in user_info train_label predict_label twd_transfer crypto_transfer usdt_swap usdt_twd_trading; do
  require_file "${PROJECT_ROOT}/data/aws_event/clean/${name}.parquet"
done

echo "[stop] terminating stale official pipeline processes"
pkill -f "python -m official.pipeline" 2>/dev/null || true
pkill -f "python -m official.train" 2>/dev/null || true
pkill -f "python -m official.validate" 2>/dev/null || true
pkill -f "python -m official.score" 2>/dev/null || true

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  echo "[stop] killing existing tmux session ${SESSION_NAME}"
  tmux kill-session -t "${SESSION_NAME}"
fi

echo "[clean] removing official-only artifacts"
mkdir -p "${ARTIFACT_DIR}/official_features" "${ARTIFACT_DIR}/models" "${ARTIFACT_DIR}/reports" "${ARTIFACT_DIR}/predictions" "${LOG_DIR}"
rm -f "${ARTIFACT_DIR}/official_features/"*
rm -f "${ARTIFACT_DIR}/predictions/official_predict_scores.parquet" "${ARTIFACT_DIR}/predictions/official_predict_scores.csv"
rm -f "${ARTIFACT_DIR}/reports/official_data_contract_report.json" "${ARTIFACT_DIR}/reports/official_validation_report.json" "${ARTIFACT_DIR}/reports/official_shadow_report.json"
rm -f "${ARTIFACT_DIR}/models/official_lgbm_"*.pkl "${ARTIFACT_DIR}/models/official_lgbm_"*.json
rm -f "${ARTIFACT_DIR}/models/official_iforest_"*.pkl "${ARTIFACT_DIR}/models/official_iforest_"*.json
: > "${LOG_FILE}"

RUN_CMD=$(cat <<'EOF'
set -euo pipefail
cd /home/a0210/projects/sideProject/bitoguard_project_bundle/bitoguard_core
source .venv/bin/activate
export PYTHONPATH=.
{
  echo "[start] $(date --iso-8601=seconds) official.pipeline"
  python -m official.pipeline
}
status=$?
echo "[exit_code] ${status} $(date --iso-8601=seconds)"
exit "${status}"
EOF
)

echo "[start] launching tmux session ${SESSION_NAME}"
tmux new-session -d -s "${SESSION_NAME}" "bash -lc '${RUN_CMD}' 2>&1 | tee -a '${LOG_FILE}'"

echo "[done] official pipeline restarted in tmux"
echo "session: ${SESSION_NAME}"
echo "log: ${LOG_FILE}"
echo "monitor:"
echo "  tmux attach -t ${SESSION_NAME}"
echo "  tmux capture-pane -pt ${SESSION_NAME} | tail -n 100"
echo "  tail -f ${LOG_FILE}"
