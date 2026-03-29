#!/bin/bash
# ============================================================
# SAGA on itiger — vLLM + CLI 全流程作业脚本
# 用途：在计算节点启动 vLLM 服务，然后跑 SAGA CLI
# 优势：vLLM 比 Ollama 快 3-5 倍（continuous batching + PagedAttention）
# ============================================================
#SBATCH --job-name=saga_vllm
#SBATCH --partition=bigTiger
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=/project/jding2/saga_logs/%j.out
#SBATCH --error=/project/jding2/saga_logs/%j.err

echo "============================================"
echo "  SAGA + vLLM on $(hostname)"
echo "  GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
echo "  时间: $(date)"
echo "============================================"

# --- 环境变量 ---
export SAGA_DIR=/project/jding2/SAGA
export VLLM_PORT=8000
export HF_HOME=/project/jding2/.cache/huggingface
export TRANSFORMERS_CACHE=/project/jding2/.cache/huggingface
# 模型名（Qwen2.5-3B-Instruct 是 HuggingFace 上的对应模型）
export VLLM_MODEL="Qwen/Qwen2.5-3B-Instruct"

# --- 安装 vLLM（首次运行时安装，之后跳过）---
if ! python3 -c "import vllm" 2>/dev/null; then
    echo "[SETUP] 安装 vLLM..."
    pip3 install --user vllm 2>&1 | tail -5
fi

# --- 启动 vLLM 服务 ---
echo "[VLLM] 启动 vLLM 服务 (model=$VLLM_MODEL, port=$VLLM_PORT)..."
python3 -m vllm.entrypoints.openai.api_server \
    --model $VLLM_MODEL \
    --port $VLLM_PORT \
    --dtype auto \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.90 \
    --quantization fp8 \
    --max-num-seqs 256 \
    --disable-log-requests \
    &
VLLM_PID=$!
echo "[VLLM] PID=$VLLM_PID, 等待模型加载..."

# 等 vLLM 启动（最多等 5 分钟）
for i in $(seq 1 60); do
    if curl -s http://localhost:$VLLM_PORT/v1/models > /dev/null 2>&1; then
        echo "[VLLM] 服务就绪! (${i}0秒)"
        break
    fi
    sleep 10
done

# 验证
curl -s http://localhost:$VLLM_PORT/v1/models | python3 -m json.tool 2>/dev/null || echo "[ERROR] vLLM 启动失败"

# --- 更新 SAGA .env 指向 vLLM ---
cd $SAGA_DIR
cat > .env << ENVEOF
SAGA_LLM_BACKEND=vllm
SAGA_OPENAI_BASE_URL=http://localhost:${VLLM_PORT}/v1
SAGA_OPENAI_MODEL=${VLLM_MODEL}
SAGA_OPENAI_API_KEY=not-needed
SAGA_LLM_TEMPERATURE=0.7
SAGA_LLM_TIMEOUT=60
SAGA_AGENT_CONCURRENCY=256
SAGA_OUTPUT_DIR=./output
SAGA_LOG_LEVEL=INFO
SAGA_VERBOSE=true
ENVEOF

# --- 运行 SAGA CLI ---
echo ""
echo "[SAGA] 开始运行..."
CONFIG=${1:-none}

if [ "$CONFIG" != "none" ] && [ -f "$CONFIG" ]; then
    echo "[SAGA] YAML 批量模式: $CONFIG"
    python3 saga_cli.py --config "$CONFIG"
else
    # 默认：1000 节点 30 天金融场景
    NODES=${2:-1000}
    DAYS=${3:-30}
    DOMAIN=${4:-finance}
    echo "[SAGA] 单次运行: nodes=$NODES days=$DAYS domain=$DOMAIN"
    python3 saga_cli.py \
        --nodes $NODES \
        --days $DAYS \
        --domain $DOMAIN \
        --seed 42 \
        --output /project/jding2/saga_output/run_${SLURM_JOB_ID}
fi

echo ""
echo "[SAGA] 完成! 输出目录: /project/jding2/saga_output/"
echo "[SAGA] 结束时间: $(date)"

# --- 清理 vLLM ---
kill $VLLM_PID 2>/dev/null
wait $VLLM_PID 2>/dev/null
echo "[VLLM] 已关闭"
