#!/bin/bash
# ============================================================
# SAGA on itiger — 批量提交所有实验
# ============================================================
echo "提交 SAGA 实验到 itiger (bigTiger 分区)..."
mkdir -p /project/jding2/saga_logs

# 每个实验提交一个独立 GPU 作业
sbatch slurm/run_vllm.sh experiments/exp_fidelity_finance.yaml
sbatch slurm/run_vllm.sh experiments/exp_scalability.yaml
sbatch slurm/run_vllm.sh experiments/exp_ablation.yaml
sbatch slurm/run_vllm.sh experiments/exp_controllability.yaml
sbatch slurm/run_vllm.sh experiments/exp_gamma_control.yaml
sbatch slurm/run_vllm.sh experiments/exp_mock_vs_llm.yaml
sbatch slurm/run_vllm.sh experiments/exp_multi_domain.yaml

echo "已提交 7 个实验。查看状态: squeue -u \$USER"
