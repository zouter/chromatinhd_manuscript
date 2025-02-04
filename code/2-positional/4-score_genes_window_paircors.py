import numpy as np
import pandas as pd

import matplotlib.pyplot as plt
import matplotlib as mpl

import seaborn as sns

sns.set_style("ticks")

import pickle

import scanpy as sc

import torch

import tqdm.auto as tqdm
import xarray as xr

import chromatinhd as chd

device = "cuda:0"
# device = "cpu"

folder_root = chd.get_output()
folder_data = folder_root / "data"

# transcriptome
# dataset_name = "lymphoma"
dataset_name = "pbmc10k"
# dataset_name = "pbmc10k_gran"
# dataset_name = "pbmc3k"
# dataset_name = "e18brain"
folder_data_preproc = folder_data / dataset_name

transcriptome = chd.data.Transcriptome(folder_data_preproc / "transcriptome")

# fragments

splitter = "random_5fold"
promoter_name, window = "10k10k", np.array([-10000, 10000])
outcome_source = "counts"
prediction_name = "v20_initdefault"

splitter = "permutations_5fold5repeat"
promoter_name, window = "100k100k", np.array([-100000, 100000])
outcome_source = "magic"
prediction_name = "v20_initdefault"
n_repeats = 1

# splitter = "permutations_5fold5repeat"
# promoter_name, window = "10k10k", np.array([-10000, 10000])
# outcome_source = "magic"
# prediction_name = "v20"
# prediction_name = "v21"
# n_repeats = 100

promoters = pd.read_csv(
    folder_data_preproc / ("promoters_" + promoter_name + ".csv"), index_col=0
)
window_width = window[1] - window[0]

fragments = chd.data.Fragments(folder_data_preproc / "fragments" / promoter_name)
fragments.obs.index.name = "cell"

# create design to run
from design import get_design, get_folds_inference


class Prediction(chd.flow.Flow):
    pass


# folds & minibatching
folds = pickle.load((fragments.path / "folds" / (splitter + ".pkl")).open("rb"))
folds, cellxgene_batch_size = get_folds_inference(fragments, folds, n_cells_step=2000)
folds = folds  # [:1]

# design
from design import get_design, get_folds_training

design = get_design(transcriptome, fragments)


def select_window(coordinates, window_start, window_end):
    return ~((coordinates[:, 0] < window_end) & (coordinates[:, 1] > window_start))


assert (
    select_window(np.array([[-100, 200], [-300, -100]]), -50, 50)
    == np.array([False, True])
).all()
assert (
    select_window(np.array([[-100, 200], [-300, -100]]), -310, -309)
    == np.array([True, True])
).all()
assert (
    select_window(np.array([[-100, 200], [-300, -100]]), 201, 202)
    == np.array([True, True])
).all()
assert (
    select_window(np.array([[-100, 200], [-300, -100]]), -200, 20)
    == np.array([False, False])
).all()

Scorer2 = chd.scoring.prediction.Scorer2

design_row = design[prediction_name]

fragments.window = window
design_row["loader_parameters"]["cellxgene_batch_size"] = cellxgene_batch_size
print(prediction_name)
prediction = chd.flow.Flow(
    chd.get_output()
    / "prediction_positional"
    / dataset_name
    / promoter_name
    / splitter
    / prediction_name
)

# loaders
if "loaders" in globals():
    loaders.terminate()
    del loaders
    import gc

    gc.collect()

loaders = chd.loaders.LoaderPool(
    design_row["loader_cls"],
    design_row["loader_parameters"],
    n_workers=20,
    shuffle_on_iter=False,
)

# load all models
models = [
    pickle.load(open(prediction.path / ("model_" + str(fold_ix) + ".pkl"), "rb"))
    for fold_ix, fold in enumerate(folds)
]
outcome = torch.from_numpy(transcriptome.adata.layers["magic"])

folds = pickle.load((fragments.path / "folds" / (splitter + ".pkl")).open("rb"))
folds, cellxgene_batch_size = get_folds_inference(fragments, folds, n_cells_step=2000)
folds = folds

# load nothing scoring
scorer_folder = prediction.path / "scoring" / "nothing"
nothing_scoring = chd.scoring.prediction.Scoring.load(scorer_folder)

from chromatinhd.scoring.prediction.filterers import (
    WindowPairFilterer,
    WindowPairBaselineFilterer,
)

scores_dir_window = prediction.path / "scoring" / "window"

genes_all = fragments.var.index
genes_all_oi = fragments.var.index
genes_all_oi = (
    nothing_scoring.genescores.mean("model")
    .sel(phase=["test", "validation"])
    .mean("phase")
    .sel(i=0)
    .to_pandas()
    .sort_values("cor", ascending=False)
    .index
)
# genes_all_oi = (
#     nothing_scoring.genescores.mean("model")
#     .sel(phase=["test", "validation"])
#     .mean("phase")
#     .sel(i=0)
#     .to_pandas()
#     .query("cor > 0.4")
#     .sort_values("cor", ascending=False)
#     .index
# )
# genes_all_oi = transcriptome.var.query("symbol == 'BCL2'").index
print(len(genes_all_oi))

design = pd.DataFrame({"gene": genes_all_oi})
design["force"] = False

for gene, subdesign in design.groupby("gene", sort=False):
    genes_oi = genes_all == gene
    scores_folder = prediction.path / "scoring" / "pairwindow_gene" / gene
    scores_folder.mkdir(exist_ok=True, parents=True)

    subdesign_row = subdesign.iloc[0]
    force = subdesign_row["force"] or not (scores_folder / "interaction.pkl").exists()

    if force:
        print(gene)
        folds_filtered, cellxgene_batch_size = get_folds_inference(
            fragments, folds, n_cells_step=2000, genes_oi=genes_oi
        )

        Scorer2 = chd.scoring.prediction.Scorer2
        window_scorer = Scorer2(
            models,
            folds_filtered[: len(models)],
            loaders,
            outcome,
            fragments.var.index[genes_oi],
            fragments.obs.index,
            device=device,
        )
        window_filterer = chd.scoring.prediction.filterers.WindowFilterer(
            window, window_size=100
        )
        window_scoring = window_scorer.score(
            filterer=window_filterer,
            nothing_scoring=nothing_scoring,
        )

        cellgenedeltacors = window_scoring.cellgenedeltacors

        cors = []
        for x in tqdm.tqdm(cellgenedeltacors):
            cors.append(np.corrcoef(x.sel(gene=gene).values))
        cors = np.stack(cors)
        cors[np.isnan(cors)] = 0

        random_cors = []
        for i in tqdm.tqdm(range(n_repeats)):
            random_cors_ = []
            for x in cellgenedeltacors:
                random_cors_.append(
                    np.corrcoef(
                        x.sel(gene=gene).values,
                        x.sel(gene=gene).values[:, np.random.permutation(x.shape[1])],
                    )[x.shape[0] :, : x.shape[0]]
                )
            random_cors.append(random_cors_)
        random_cors = np.stack(random_cors)
        random_cors[np.isnan(random_cors)] = 0

        random_cors = np.concatenate(
            [
                random_cors,
                np.swapaxes(random_cors, -1, -2),
            ],
            0,
        )

        cors_flattened = cors.reshape((cors.shape[0], -1))
        interaction = pd.DataFrame(
            {
                "cor": cors_flattened.mean(0),
                "window_ix1": np.tile(
                    np.arange(cors.shape[1])[:, None], cors.shape[1]
                ).flatten(),
                "window_ix2": np.tile(
                    np.arange(cors.shape[1])[:, None], cors.shape[1]
                ).T.flatten(),
                "window1": np.tile(
                    window_scoring.genescores.coords["window"].values[:, None],
                    len(window_scoring.genescores.coords["window"].values),
                ).flatten(),
                "window2": np.tile(
                    window_scoring.genescores.coords["window"].values[:, None],
                    len(window_scoring.genescores.coords["window"].values),
                ).T.flatten(),
            }
        )
        interaction["distance"] = np.abs(
            interaction["window1"] - interaction["window2"]
        )
        interaction["pval"] = (1 - (cors >= random_cors).mean(0).mean(0)).flatten()
        # interaction["pval"] = 1 - (cors.mean(0) > random_cors.mean(1)).mean(0).flatten()
        # interaction = interaction.query("distance > 500")
        interaction["deltacor1"] = (
            window_scoring.genescores.sel(gene=gene)
            .mean("model")
            .sel(phase="test")["deltacor"]
            .to_pandas()[interaction["window1"]]
            .values
        )
        interaction["deltacor2"] = (
            window_scoring.genescores.sel(gene=gene)
            .mean("model")
            .sel(phase="test")["deltacor"]
            .to_pandas()[interaction["window2"]]
            .values
        )
        interaction["lost1"] = (
            window_scoring.genescores.sel(gene=gene)
            .mean("model")
            .sel(phase="test")["lost"]
            .to_pandas()[interaction["window1"]]
            .values
        )
        interaction["lost2"] = (
            window_scoring.genescores.sel(gene=gene)
            .mean("model")
            .sel(phase="test")["lost"]
            .to_pandas()[interaction["window2"]]
            .values
        )

        import statsmodels.stats.multitest

        interaction["qval"] = statsmodels.stats.multitest.fdrcorrection(
            interaction["pval"]
        )[1]

        interaction.to_pickle(scores_folder / "interaction.pkl")
    else:
        print(gene, "already done")
