import pandas as pd
import numpy as np
import torch
import tqdm.auto as tqdm

import chromatinhd as chd
import chromatinhd.data
import chromatinhd.loaders.fragmentmotif
import chromatinhd.loaders.minibatching

import pickle

device = "cuda:0"

folder_root = chd.get_output()
folder_data = folder_root / "data"

# transcriptome
# dataset_name = "lymphoma"
dataset_name = "pbmc10k"
# dataset_name = "e18brain"
# dataset_name = "pbmc10k+lymphoma"
# dataset_name = "lymphoma+pbmc10k"
folder_data_preproc = folder_data / dataset_name

transcriptome = chromatinhd.data.Transcriptome(folder_data_preproc / "transcriptome")

# fragments
# promoter_name, window = "1k1k", np.array([-1000, 1000])
promoter_name, window = "10k10k", np.array([-10000, 10000])
promoters = pd.read_csv(
    folder_data_preproc / ("promoters_" + promoter_name + ".csv"), index_col=0
)
window_width = window[1] - window[0]

fragments = chromatinhd.data.Fragments(
    folder_data_preproc / "fragments" / promoter_name
)

# motifscan
motifscan_folder = chd.get_output() / "motifscans" / dataset_name / promoter_name
# motifscan_folder = chd.get_output() / "motifscans" / dataset_name / promoter_name / "cutoff_001"
motifscan = chd.data.Motifscan(motifscan_folder)

# create design to run
from design import get_design, get_folds_training

design = get_design(dataset_name, transcriptome, motifscan, fragments, window=window)
# design = {k:design[k] for k in [
# "v4",
# "v4_dummy",
# "v4_1k-1k",
# "v4_10-10",
# "v4_150-0",
# "v4_0-150",
# "v4_nn",
# "v4_nn_dummy1",
# "v4_nn_1k-1k",
# "v4_split",
# "v4_nn_split",
# "v4_lw_split",
# "v4_nn_lw",
# "v4_nn_lw_split",
# "v4_nn_lw_split",
# "v4_nn_lw_split_mean",
# "v4_150-0_nn",
# "v4_150-100-50-0_nn",
# "v4_150-100-50-0",
# "v4_1k-150-0_nn",
# "v4_cutoff001"
# "v4_nn_cutoff001",
# "v4_prom",
# "v4_prom_nn"
# ]}
design = design["titr"]
design = {k: design[k] for k in list(design.keys())[30:]}
# fold_slice = slice(0, 1)
fold_slice = slice(0, 5)
# fold_slice = slice(1, 5)


# folds & minibatching
folds = pickle.load((fragments.path / "folds.pkl").open("rb"))
folds = get_folds_training(fragments, folds)

# loss
cos = torch.nn.CosineSimilarity(dim=0)
loss = lambda x_1, x_2: -cos(x_1, x_2).mean()


def paircor(x, y, dim=0, eps=0.1):
    divisor = (y.std(dim) * x.std(dim)) + eps
    cor = ((x - x.mean(dim, keepdims=True)) * (y - y.mean(dim, keepdims=True))).mean(
        dim
    ) / divisor
    return cor


loss = lambda x, y: -paircor(x, y).mean() * 100


class Prediction(chd.flow.Flow):
    pass


for prediction_name, design_row in design.items():
    print(prediction_name)
    prediction = chd.flow.Flow(
        chd.get_output()
        / "prediction_sequence"
        / dataset_name
        / promoter_name
        / prediction_name
    )

    # loaders
    print("collecting...")
    if "loaders" in globals():
        loaders.terminate()
        del loaders
        import gc

        gc.collect()
    if "loaders_validation" in globals():
        loaders_validation.terminate()
        del loaders_validation
        import gc

        gc.collect()
    print("collected")
    loaders = chd.loaders.LoaderPool(
        design_row["loader_cls"], design_row["loader_parameters"], n_workers=20
    )
    print("haha!")
    loaders_validation = chd.loaders.LoaderPool(
        design_row["loader_cls"], design_row["loader_parameters"], n_workers=5
    )
    print("finish")
    loaders_validation.shuffle_on_iter = False

    models = []
    for fold_ix, fold in [(fold_ix, fold) for fold_ix, fold in enumerate(folds)][
        fold_slice
    ]:
        # model
        model = design_row["model_cls"](
            **design_row["model_parameters"], loader=loaders.loaders[0]
        )

        # optimizer
        params = model.get_parameters()

        # optimization
        optimize_every_step = 1
        # lr = 1e-2
        lr = 1e-3
        # lr = 5e-3
        optim = torch.optim.Adam(params, lr=lr, weight_decay=lr / 10)
        n_epochs = 50
        checkpoint_every_epoch = 30

        # initialize loaders
        loaders.initialize(fold["minibatches_train"])
        loaders_validation.initialize(fold["minibatches_validation_trace"])

        # train
        import chromatinhd.train

        outcome = transcriptome.X.dense()
        trainer = chd.train.Trainer(
            model,
            loaders,
            loaders_validation,
            outcome,
            loss,
            optim,
            checkpoint_every_epoch=checkpoint_every_epoch,
            optimize_every_step=optimize_every_step,
            n_epochs=n_epochs,
            device=device,
        )
        trainer.train()

        model = model.to("cpu")
        pickle.dump(
            model, open(prediction.path / ("model_" + str(fold_ix) + ".pkl"), "wb")
        )

        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        plotdata_validation = (
            pd.DataFrame(trainer.trace.validation_steps)
            .groupby("checkpoint")
            .mean()
            .reset_index()
        )
        plotdata_train = (
            pd.DataFrame(trainer.trace.train_steps)
            .groupby("checkpoint")
            .mean()
            .reset_index()
        )
        ax.plot(
            plotdata_validation["checkpoint"], plotdata_validation["loss"], label="test"
        )
        # ax.plot(plotdata_train["checkpoint"], plotdata_train["loss"], label = "train")
        ax.legend()
        fig.savefig(prediction.path / ("trace_" + str(fold_ix) + ".png"))
        plt.close()
