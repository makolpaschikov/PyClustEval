# Update: Flower implementation
We now have an app on the [flower hub](https://flower.ai/apps/swiergarst/fed-kmeans-flower/)!

# Federated K-means clustering (FKM)

this is the repository for the code corresponding to the article ["Federated K-means clustering"](https://arxiv.org/abs/2310.01195). Algorithm implementation can be found in [fed_kmeans.py](fed_kmeans.py)  The repo holds three notebooks:
- [comparison.ipynb](comparison.ipynb): this holds the main experiment runs/settings.
- [figures.ipynb](figures.ipynb): code used to generate the figures in the paper.
- [synthetic_dataset.ipynb](synthetic_dataset.ipynb): the notebook used to generate the synthetic dataset(s).

We also used a High Performance Cluster (HPC) with a slurm scheduler for some experiments. code for this can be foun in the [HPC](HPC/) folder.
