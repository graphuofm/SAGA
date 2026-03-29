#!/bin/bash
# ============================================================
# SAGA 全部实验 — itiger H100 一键运行
# 修复版：补全所有实验、vLLM 启动参数修正、错误处理
# 预计总时间：2-4 小时（取决于 scalability 100K）
# 用法：sbatch slurm_run_all_experiments.sh
# ============================================================
#SBATCH --job-name=saga_all
#SBATCH --partition=bigTiger
#SBATCH --gres=gpu:h100_80gb:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=/project/jding2/saga_logs/all_%j.out
#SBATCH --error=/project/jding2/saga_logs/all_%j.err

set -e

echo "============================================"
echo "  SAGA All Experiments on $(hostname)"
echo "  GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
echo "  Time: $(date)"
echo "  Job ID: $SLURM_JOB_ID"
echo "============================================"

export SAGA_DIR=/project/jding2/SAGA
export VLLM_PORT=8000
export HF_HOME=/project/jding2/.cache/huggingface
export VLLM_MODEL="Qwen/Qwen2.5-3B-Instruct"

# 创建日志目录
mkdir -p /project/jding2/saga_logs
mkdir -p $SAGA_DIR/output/final

# --- 杀掉可能残留的 vLLM 进程 ---
pkill -f "vllm.entrypoints" 2>/dev/null || true
sleep 2

# --- 启动 vLLM ---
echo "[VLLM] 启动 vLLM on port $VLLM_PORT ..."
python3 -m vllm.entrypoints.openai.api_server \
    --model $VLLM_MODEL \
    --port $VLLM_PORT \
    --dtype half \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.92 \
    --max-num-seqs 256 \
    --disable-log-requests \
    > /project/jding2/saga_logs/vllm_${SLURM_JOB_ID}.log 2>&1 &
VLLM_PID=$!

# 等 vLLM 启动（最多 5 分钟）
VLLM_READY=0
for i in $(seq 1 60); do
    if curl -s http://localhost:$VLLM_PORT/v1/models > /dev/null 2>&1; then
        echo "[VLLM] Ready! (waited ${i}0 seconds)"
        VLLM_READY=1
        break
    fi
    sleep 10
done

if [ $VLLM_READY -eq 0 ]; then
    echo "[ERROR] vLLM 启动超时！检查日志: /project/jding2/saga_logs/vllm_${SLURM_JOB_ID}.log"
    # 尝试换端口
    VLLM_PORT=8001
    echo "[VLLM] 尝试端口 $VLLM_PORT ..."
    if curl -s http://localhost:$VLLM_PORT/v1/models > /dev/null 2>&1; then
        echo "[VLLM] 在端口 $VLLM_PORT 找到已运行的 vLLM"
        VLLM_READY=1
    else
        echo "[FATAL] vLLM 完全不可用，退出"
        exit 1
    fi
fi

# --- 配置 .env ---
cd $SAGA_DIR
cat > .env << ENVEOF
SAGA_LLM_BACKEND=vllm
SAGA_OPENAI_BASE_URL=http://localhost:${VLLM_PORT}/v1
SAGA_OPENAI_MODEL=${VLLM_MODEL}
SAGA_OPENAI_API_KEY=not-needed
SAGA_LLM_TEMPERATURE=0.7
SAGA_LLM_TIMEOUT=120
SAGA_LLM_MAX_RETRIES=3
SAGA_AGENT_CONCURRENCY=256
SAGA_OUTPUT_DIR=./output
SAGA_LOG_LEVEL=INFO
SAGA_VERBOSE=false
ENVEOF

echo "[ENV] .env 已写入 (vLLM port=$VLLM_PORT)"

# ============================================================
# 运行实验的辅助函数
# ============================================================
run_experiment() {
    local exp_file="$1"
    local name=$(basename "$exp_file" .yaml)
    echo ""
    echo "========== Experiment: $name =========="
    echo "  Config: $exp_file"
    echo "  Start: $(date)"
    
    if python3 saga_cli.py --config "$exp_file"; then
        echo "  ✓ $name 完成 $(date)"
    else
        echo "  ✗ $name 失败！继续下一个..."
    fi
}

# ============================================================
# 实验 0：对比实验（SAGA vs NetworkX vs igraph vs SAGA-LLM）
# ============================================================
echo ""
echo "========== Experiment 0: Comparison =========="
echo "  Start: $(date)"
if python3 experiments/run_comparison.py; then
    echo "  ✓ Comparison 完成"
else
    echo "  ✗ Comparison 失败，继续..."
fi

# ============================================================
# 实验 1-8：YAML 批量实验（全部跑完）
# ============================================================
EXPERIMENTS=(
    "experiments/exp_fidelity.yaml"
    "experiments/exp_fidelity_finance.yaml"
    "experiments/exp_scalability.yaml"
    "experiments/exp_controllability.yaml"
    "experiments/exp_ablation.yaml"
    "experiments/exp_multi_domain.yaml"
    "experiments/exp_mock_vs_llm.yaml"
    "experiments/exp_gamma_control.yaml"
)

for exp in "${EXPERIMENTS[@]}"; do
    if [ -f "$exp" ]; then
        run_experiment "$exp"
    else
        echo "[WARN] 跳过不存在的实验: $exp"
    fi
done

# ============================================================
# 收集所有 summary.csv 到 output/final/
# ============================================================
echo ""
echo "========== Collecting Results =========="
for dir in output/*/; do
    dirname=$(basename "$dir")
    if [ "$dirname" = "final" ] || [ "$dirname" = "fix_verify" ]; then
        continue
    fi
    if [ -f "$dir/summary.csv" ]; then
        cp "$dir/summary.csv" "output/final/${dirname}_summary.csv"
        echo "  ✓ ${dirname}_summary.csv"
    fi
done
cp output/comparison/comparison.csv output/final/ 2>/dev/null && echo "  ✓ comparison.csv"

# 合并所有 summary 到一个总表
echo ""
echo "--- 合并总表 ---"
python3 -c "
import csv, os, glob

all_rows = []
header = None
for f in sorted(glob.glob('output/final/*_summary.csv')):
    with open(f) as fh:
        reader = csv.DictReader(fh)
        if header is None:
            header = reader.fieldnames
        for row in reader:
            row['_experiment'] = os.path.basename(f).replace('_summary.csv', '')
            all_rows.append(row)

if all_rows and header:
    all_keys = ['_experiment'] + [k for k in header if k != '_experiment']
    with open('output/final/ALL_RESULTS.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
        w.writeheader()
        w.writerows(all_rows)
    print('  ✓ ALL_RESULTS.csv ({} rows)'.format(len(all_rows)))
" 2>/dev/null || echo "  合并失败（非致命）"

# 打包结果
echo ""
cd /project/jding2
tar czf saga_results_$(date +%Y%m%d).tar.gz SAGA/output/final/
echo "✓ 结果已打包: /project/jding2/saga_results_$(date +%Y%m%d).tar.gz"

echo ""
echo "============================================"
echo "  All experiments done!"
echo "  Results: $SAGA_DIR/output/final/"
echo "  End: $(date)"
echo "============================================"

# --- 清理 vLLM ---
kill $VLLM_PID 2>/dev/null
wait $VLLM_PID 2>/dev/null
echo "[VLLM] Closed"
