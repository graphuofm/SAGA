#!/bin/bash
#SBATCH --job-name=saga_dbg
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/scratch/jding/saga_logs/%j.out

module load python/3.10
cd /project/jding/SAGA
source .venv/bin/activate

python saga_cli.py --mode mock --nodes 100 --days 7 --domain finance \
    --output /scratch/jding/saga_output/debug_$SLURM_JOB_ID
