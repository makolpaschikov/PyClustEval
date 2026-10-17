from __future__ import annotations

import argparse

from clustering_eval.datasets.mnist import load_mnist_full, load_mnist_10k


def main() -> None:
    parser = argparse.ArgumentParser(description="Download/cache MNIST for PyClustEval")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Load the full 70k corpus after caching instead of the 10k benchmark subset",
    )
    args = parser.parse_args()
    dataset = load_mnist_full() if args.full else load_mnist_10k()
    print(
        f"{dataset.name} ready: {dataset.X.shape[0]} samples x "
        f"{dataset.X.shape[1]} features, "
        f"{len(set(dataset.y.tolist())) if dataset.y is not None else 0} classes"
    )
    print(f"Cached directory: {dataset.metadata['data_directory']}")
    print(f"Source: {dataset.metadata['source_url']}")
    print(f"Download mirror: {dataset.metadata['download_mirror']}")


if __name__ == "__main__":
    main()
