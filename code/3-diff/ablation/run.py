import pandas as pd
import numpy as np
import torch

import chromatinhd as chd
import chromatinhd.data
import matplotlib.pyplot as plt

import pickle
import copy
import tqdm.auto as tqdm

from design import (
    dataset_splitter_method_combinations as design,
)
from params import params

device = "cuda:0"

dry_run = False

design = design.query("dataset == 'pbmc10k/subsets/top250'")
design = design.query("clustering == 'leiden_0.1'")
# design = design.query("regions == '10k10k'")
# design = design.query("method == 'radial_binary_1000-31frequencies_splitdistance_wd0'")

design = design.copy()
design["force"] = False
# design["force"] = True
# dry_run = True

print(design)

for (dataset_name, regions_name), subdesign in design.groupby(["dataset", "regions"]):
    print(f"{dataset_name=}")
    dataset_folder = chd.get_output() / "datasets" / dataset_name
    fragments = chromatinhd.data.Fragments(dataset_folder / "fragments" / regions_name)

    for (splitter, clustering_name), subdesign in subdesign.groupby(["splitter", "clustering"]):
        # folds & minibatching
        folds = chd.data.folds.Folds(dataset_folder / "folds" / splitter)

        clustering = chromatinhd.data.clustering.Clustering(dataset_folder / "latent" / clustering_name)

        for method_name, subdesign in subdesign.groupby("method"):
            method_info = params[method_name]

            print(subdesign.iloc[0])

            prediction = chd.flow.Flow(
                chd.get_output() / "diff" / dataset_name / regions_name / splitter / clustering_name / method_name,
                reset=subdesign.iloc[0]["force"],
            )
            performance = chd.models.diff.interpret.Performance.create(
                path=prediction.path / "scoring" / "performance",
                folds=folds,
                fragments=fragments,
            )

            force = subdesign["force"].iloc[0]
            if performance.scores["scored"].sel_xr().all() and not force:
                continue

            models = chd.models.diff.model.binary.Models.create(
                fragments=fragments,
                clustering=clustering,
                folds=folds,
                reset=force,
                model_params={**method_info["model_params"]},
                train_params=method_info["train_params"],
            )

            if dry_run:
                continue

            models.train_models()

            performance.score(models)
