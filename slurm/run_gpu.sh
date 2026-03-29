#!/bin/bash
#SBATCH --job-name=saga
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=/scratch/jding/saga_logs/%j.out
#SBATCH --error=/scratch/jding/saga_logs/%j.err

module load python/3.10 cuda/12.0
cd /project/jding/SAGA
source .venv/bin/activate

# 在计算节点启动 Ollama
./bin/ollama serve &
OLLAMA_PID=$!
sleep 15

# 执行
CONFIG=${1:-experiments/exp_scalability.yaml}
python saga_cli.py --config $CONFIG

kill $OLLAMA_PID
