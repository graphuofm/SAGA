#!/bin/bash
echo "Submitting all SAGA experiments..."
mkdir -p /scratch/jding/saga_logs
sbatch slurm/run_gpu.sh experiments/exp_fidelity_finance.yaml
sbatch slurm/run_gpu.sh experiments/exp_scalability.yaml
sbatch slurm/run_gpu.sh experiments/exp_ablation.yaml
sbatch slurm/run_gpu.sh experiments/exp_controllability.yaml
sbatch slurm/run_gpu.sh experiments/exp_gamma_control.yaml
sbatch slurm/run_gpu.sh experiments/exp_mock_vs_llm.yaml
sbatch slurm/run_gpu.sh experiments/exp_multi_domain.yaml
echo "All submitted. Check: squeue -u \$USER"
