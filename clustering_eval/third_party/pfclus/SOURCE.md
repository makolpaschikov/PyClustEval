# p-FClus source

- Supplied archive: `p-FClus-main.zip`
- ZIP embedded commit: `3fd7c09d98fb23c9807931c6363ad1181eb283f1`
- Paper: *Fair Federated Data Clustering through Personalization: Bridging the Gap between Diverse Data Distributions* (arXiv:2407.04302)
- Executed source: `main_algo/p-FClus.py` (`pFClus`, `sgd_scipy`)
- The vendored `p-FClus.py` is byte-for-byte identical to the supplied archive.
- The original script has no `if __name__ == "__main__"` guard and immediately tries to load `adult.csv`. The PyClustEval adapter therefore parses the unchanged file and executes only the two author function definitions, injecting their original globals (`numpy`, `KMeans`, and `total_classes`) at runtime.
