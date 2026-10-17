from __future__ import annotations

from clustering_eval.datasets.dry_bean import load_dry_bean


def main() -> None:
    dataset = load_dry_bean()
    print(
        f"Dry Bean ready: {dataset.X.shape[0]} samples x "
        f"{dataset.X.shape[1]} features, "
        f"{len(set(dataset.y.tolist())) if dataset.y is not None else 0} classes"
    )
    print(f"Cached file: {dataset.metadata['data_path']}")
    print(f"Source: {dataset.metadata['source_url']}")
    print(f"DOI: {dataset.metadata['doi']}")


if __name__ == "__main__":
    main()
