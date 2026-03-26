#!/bin/bash
# BitoGuard E15 — 分散式 Nested HPO
#
# 用法:
#   Machine 1: ./scripts/run_nested_hpo_distributed.sh 0 1 2
#   Machine 2: ./scripts/run_nested_hpo_distributed.sh 3 4
#
# 或一台跑全部:
#   ./scripts/run_nested_hpo_distributed.sh 0 1 2 3 4
#
# 完成後執行聚合:
#   cd bitoguard_core && PYTHONPATH=. python -m official.nested_hpo --aggregate

set -euo pipefail

FOLDS="${@:?用法: $0 <fold_ids...>  例: $0 0 1 2}"
N_TRIALS="${N_TRIALS:-30}"
INNER_FOLDS="${INNER_FOLDS:-3}"
OPTUNA_JOBS="${OPTUNA_JOBS:-2}"

cd "$(dirname "$0")/../bitoguard_core"

echo "========================================"
echo "BitoGuard Nested HPO — 分散式執行"
echo "========================================"
echo "  Folds: $FOLDS"
echo "  Trials/study: $N_TRIALS"
echo "  Inner folds: $INNER_FOLDS"
echo "  Optuna jobs: $OPTUNA_JOBS"
echo "  開始時間: $(date)"
echo "========================================"

for fold in $FOLDS; do
  echo ""
  echo "[$(date)] === Outer Fold $fold 開始 ==="
  PYTHONPATH=. python -m official.nested_hpo \
    --outer-fold "$fold" \
    --n-trials "$N_TRIALS" \
    --inner-folds "$INNER_FOLDS"
  echo "[$(date)] === Outer Fold $fold 完成 ==="
done

echo ""
echo "========================================"
echo "所有指定 folds 完成！"
echo "完成時間: $(date)"
echo ""
echo "若所有 5 folds 都完成，執行聚合："
echo "  cd bitoguard_core && PYTHONPATH=. python -m official.nested_hpo --aggregate"
echo "========================================"
