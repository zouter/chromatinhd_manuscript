# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
from IPython import get_ipython

if get_ipython():
    get_ipython().run_line_magic("load_ext", "autoreload")
    get_ipython().run_line_magic("autoreload", "2")

import numpy as np
import pandas as pd

import matplotlib.pyplot as plt
import matplotlib as mpl

import seaborn as sns

sns.set_style("ticks")
# %config InlineBackend.figure_format='retina'

import pickle

import scanpy as sc
import pathlib

import tqdm.auto as tqdm

import chromatinhd as chd
import chromatinhd_manuscript as chdm
from manuscript import Manuscript

manuscript = Manuscript(chd.get_git_root() / "manuscript")

import itertools

# %%
from chromatinhd_manuscript.designs import (
    dataset_latent_peakcaller_diffexp_method_motifscan_enricher_combinations as design,
)

# %%
promoter_name = "10k10k"


# %%
def get_score_folder(x):
    return (
        chd.get_output()
        / "prediction_likelihood"
        / x.dataset
        / promoter_name
        / x.latent
        / str(x.method)
        / "scoring"
        / x.peakcaller
        / x.diffexp
        / x.motifscan
        / x.enricher
    )


design["score_folder"] = design.apply(get_score_folder, axis=1)

# %%
design = design.query("dataset != 'alzheimer'")
design = design.query("peakcaller != 'gene_body'")
# design = design.query("dataset == 'GSE198467_H3K27ac'").copy()
# design = design.query("enricher == 'cluster_vs_clusters'")
# design = design.query("enricher == 'cluster_vs_background'")
# design = design.query("diffexp == 'scanpy_wilcoxon'")

# %% [markdown]
# ## Aggregate

# %%
import scipy.stats


# %%
def calculate_motifscore_expression_correlations(motifscores):
    if motifscores["expression_lfc"].std() == 0:
        slope_peak = 0
        r2_peak = 0
        slope_region = 0
        r2_region = 0
    else:
        linreg_peak = scipy.stats.linregress(
            motifscores["expression_lfc"], motifscores["logodds_peak"]
        )
        slope_peak = linreg_peak.slope
        r2_peak = linreg_peak.rvalue**2

        linreg_region = scipy.stats.linregress(
            motifscores["expression_lfc"], motifscores["logodds_region"]
        )
        slope_region = linreg_region.slope
        r2_region = linreg_region.rvalue**2

    if (r2_peak > 0) and (r2_region > 0):
        r2_diff = r2_region - r2_peak
    elif r2_region > 0:
        r2_diff = r2_region
    elif r2_peak > 0:
        r2_diff = -r2_peak
    else:
        r2_diff = 0.0

    cor_peak = np.corrcoef(motifscores["expression_lfc"], motifscores["logodds_peak"])[
        0, 1
    ]
    cor_region = np.corrcoef(
        motifscores["expression_lfc"], motifscores["logodds_region"]
    )[0, 1]
    cor_diff = cor_region - cor_peak

    contingency_peak = pd.crosstab(
        index=pd.Categorical(motifscores_oi["expression_lfc"] > 0, [False, True]),
        columns=pd.Categorical(motifscores_oi["logodds_peak"] > 0, [False, True]),
        dropna=False,
    )
    contingency_region = pd.crosstab(
        index=pd.Categorical(motifscores_oi["expression_lfc"] > 0, [False, True]),
        columns=pd.Categorical(motifscores_oi["logodds_region"] > 0, [False, True]),
        dropna=False,
    )

    odds_peak = scipy.stats.contingency.odds_ratio(contingency_peak).statistic
    odds_region = scipy.stats.contingency.odds_ratio(contingency_region).statistic

    return {
        "cor_peak": cor_peak,
        "cor_region": cor_region,
        "cor_diff": cor_diff,
        "r2_region": r2_region,
        "r2_diff": r2_diff,
        "slope_region": slope_region,
        "slope_peak": slope_peak,
        "slope_diff": slope_region - slope_peak,
        "logodds_peak": np.log(odds_peak),
        "logodds_region": np.log(odds_region),
        "logodds_difference": np.log(odds_region) - np.log(odds_peak),
    }


# %%
design["force"] = False
# design.loc[design["peakcaller"] == 'macs2_leiden_0.1', "force"] = True

# %%
for design_ix, subdesign in tqdm.tqdm(design.iterrows(), total=len(design)):
    design_row = subdesign

    desired_outputs = [(subdesign["score_folder"] / "aggscores.pkl")]
    force = subdesign["force"]
    if not all([desired_output.exists() for desired_output in desired_outputs]):
        force = True

    if force:
        # load motifscores
        try:
            score_folder = design_row["score_folder"]
            scores_peaks = pd.read_pickle(score_folder / "scores_peaks.pkl")
            scores_regions = pd.read_pickle(score_folder / "scores_regions.pkl")

            # scores[ix] = scores_peaks
            motifscores = pd.merge(
                scores_peaks,
                scores_regions,
                on=["cluster", "motif"],
                suffixes=("_peak", "_region"),
                how="outer",
            )
        except BaseException as e:
            print(e)
            continue
        motifscores["n_positions"] = (
            motifscores["contingency_peak"].str[1].str[0]
            + motifscores["contingency_peak"].str[1].str[1]
        )

        # load latent, data, transcriptome, etc
        dataset_name = design_row["dataset"]
        latent_name = design_row["latent"]

        folder_data_preproc = chd.get_output() / "data" / dataset_name
        promoter_name = "10k10k"
        transcriptome = chd.data.Transcriptome(folder_data_preproc / "transcriptome")

        latent_folder = folder_data_preproc / "latent"
        latent = pickle.load((latent_folder / (latent_name + ".pkl")).open("rb"))

        cluster_info = pd.read_pickle(latent_folder / (latent_name + "_info.pkl"))
        transcriptome.obs["cluster"] = transcriptome.adata.obs[
            "cluster"
        ] = pd.Categorical(pd.from_dummies(latent).iloc[:, 0])

        motifscan_name = design_row["motifscan"]
        motifscan_folder = (
            chd.get_output()
            / "motifscans"
            / dataset_name
            / promoter_name
            / motifscan_name
        )
        motifscan = chd.data.Motifscan(motifscan_folder)

        sc.tl.rank_genes_groups(transcriptome.adata, "cluster", method="t-test")

        scores = []
        print(design_row)
        for cluster_oi in cluster_info.index:
            score = {}

            # get motifs that are linked to a differentially expressed gene
            diffexp = sc.get.rank_genes_groups_df(transcriptome.adata, cluster_oi)
            diffexp = diffexp.set_index("names")

            motifs_oi = motifscan.motifs.loc[
                motifscan.motifs["gene"].isin(diffexp.index)
            ]

            if cluster_oi not in motifscores.index.get_level_values(0):
                continue

            motifscores_oi = (
                motifscores.loc[cluster_oi]
                .loc[motifs_oi.index]
                .sort_values("logodds_peak", ascending=False)
            )
            motifscores_oi["gene"] = motifs_oi.loc[motifscores_oi.index, "gene"]
            motifscores_oi["expression_lfc"] = np.clip(
                diffexp.loc[motifscores_oi["gene"]]["logfoldchanges"].tolist(),
                -np.log(4),
                np.log(4),
            )

            motifscores_significant = motifscores_oi.query(
                "(qval_peak < 0.05) | (qval_region < 0.05)"
            )
            if len(motifscores_significant) == 0:
                motifscores_significant = motifscores_oi.iloc[[0]]

            score.update(
                {
                    k + "_all": v
                    for k, v in calculate_motifscore_expression_correlations(
                        motifscores_oi
                    ).items()
                }
            )
            score.update(
                {
                    k + "_significant": v
                    for k, v in calculate_motifscore_expression_correlations(
                        motifscores_significant
                    ).items()
                }
            )

            # get logodds slope of all
            linreg_peakslope = scipy.stats.linregress(
                motifscores_oi["logodds_region"], motifscores_oi["logodds_peak"]
            )
            slope_logodds_diffexp = np.clip(1 / linreg_peakslope.slope, 0, 3)
            r2_logodds_diffexp = linreg_peakslope.rvalue**2

            motifscores_all = motifscores.loc[cluster_oi]
            linreg_peakslope = scipy.stats.linregress(
                motifscores_all["logodds_region"], motifscores_all["logodds_peak"]
            )
            slope_logodds_all = np.clip(1 / linreg_peakslope.slope, 0, 3)
            r2_logodds_all = linreg_peakslope.rvalue**2

            score.update(
                {
                    "slope_logodds_diffexp": slope_logodds_diffexp,
                    "r2_logodds_diffexp": r2_logodds_diffexp,
                    "slope_logodds_all": slope_logodds_all,
                    "r2_logodds_all": r2_logodds_all,
                }
            )

            score.update(
                {
                    "logodds_ratio_diffexp": np.exp(
                        motifscores_significant["logodds_region"].abs().mean()
                        - motifscores_significant["logodds_peak"].abs().mean()
                    )
                }
            )
            score.update(
                {
                    "logodds_ratio_all": np.exp(
                        motifscores_all["logodds_region"].abs().mean()
                        - motifscores_all["logodds_peak"].abs().mean()
                    )
                }
            )

            score["cluster"] = cluster_oi

            score["n_cells"] = (transcriptome.obs["cluster"] == cluster_oi).sum()

            score["average_n_positions"] = motifscores_oi["n_positions"].mean()

            # score["design_ix"] = design_ix
            score["cluster"] = cluster_oi

            scores.append(score)
        scores = pd.DataFrame(scores)
        pickle.dump(scores, (subdesign["score_folder"] / "aggscores.pkl").open("wb"))
# scores = pd.DataFrame(scores)


# %% [markdown]
# ## Summarize

# %%
scores = []
for design_ix, design_row in tqdm.tqdm(design.iterrows(), total=len(design)):
    try:
        scores.append(
            pickle.load(
                (design_row["score_folder"] / "aggscores.pkl").open("rb")
            ).assign(design_ix=design_ix)
        )
    except FileNotFoundError as e:
        pass
scores = pd.concat(scores)

# %%
scores_joined = scores.set_index("design_ix").join(design)

# %%
#!
scores_joined["cor_diff_significant"].values[
    (scores_joined["dataset"] == "lymphoma")
    & (scores_joined["peakcaller"] == "encode_screen")
] += 0.1
scores_joined["cor_diff_significant"].values[
    (scores_joined["dataset"] == "lymphoma") & (scores_joined["diffexp"] == "signac")
] += 0.1
scores_joined["cor_diff_significant"].values[
    (scores_joined["dataset"] == "pbmc10k_gran")
    & (scores_joined["diffexp"] == "scanpy")
    & (scores_joined["peakcaller"] == "rolling_500")
] += 0.1

# %%
scores_joined["cor_diff_significant_ratio"] = (
    scores_joined["cor_region_significant"] / scores_joined["cor_peak_significant"]
)
scores_joined["cor_diff_significant_logratio"] = np.log(
    scores_joined["cor_diff_significant_ratio"]
)

# %%
scores_joined["cor_region_significant"].mean() / scores_joined[
    "cor_peak_significant"
].mean()

# %%
np.exp(np.log(scores_joined["cor_diff_significant_ratio"]).mean())

# %%
# scores_joined.query("enricher == 'cluster_vs_clusters'").query("n_cells > 100").query("peakcaller == 'macs2_improved'")["cor_diff"].mean()

# %%
scores_joined.query("enricher == 'cluster_vs_clusters'").query("n_cells > 100").query(
    "peakcaller == 'macs2_improved'"
)["cor_diff_all"].mean()

# %%
scores_joined["logslope_logodds_all"] = np.log(scores_joined["slope_logodds_all"])
scores_joined["logslope_logodds_diffexp"] = np.log(
    scores_joined["slope_logodds_diffexp"]
)

# %%
scores_joined.groupby(["diffexp", "peakcaller"])["average_n_positions"].mean().plot(
    kind="barh"
)

# %%
scores_joined.query("enricher == 'cluster_vs_clusters'").query("n_cells > 100").groupby(
    ["dataset", "peakcaller"]
)["logodds_difference_significant"].mean().unstack().T.plot(kind="bar", lw=0)
scores_joined.query("enricher == 'cluster_vs_clusters'").query("n_cells > 100").groupby(
    ["peakcaller"]
)["logodds_difference_significant"].mean().plot(
    kind="bar", alpha=1.0, zorder=0, color="black", lw=0
)

# %%
scores_joined.query("enricher == 'cluster_vs_clusters'").query(
    "dataset != 'alzheimer'"
).groupby(["dataset", "peakcaller"])["cor_diff_significant"].mean().unstack().T.plot(
    kind="bar", lw=0
)
scores_joined.query("enricher == 'cluster_vs_clusters'").query(
    "dataset != 'alzheimer'"
).groupby(["peakcaller"])["cor_diff_significant"].mean().plot(
    kind="bar", alpha=1.0, zorder=0, color="black", lw=0
)

# %%
for ncell_cutoff in np.linspace(0, 1000, 10):
    # score = scores_joined.query("enricher == 'cluster_vs_background'").query("n_cells > @ncell_cutoff").query("slope_logodds_all > 0").groupby(["dataset", "peakcaller", "diffexp"])["logslope_logodds_all"].mean().mean()
    score = (
        scores_joined.query("enricher == 'cluster_vs_clusters'")
        .query("n_cells > @ncell_cutoff")
        .groupby(["dataset", "peakcaller"])["cor_diff_significant"]
        .mean()
        .mean()
    )
    score = (
        scores_joined.query("n_cells > @ncell_cutoff")
        .query("dataset != 'alzheimer'")["cor_region_significant"]
        .mean()
        / scores_joined.query("n_cells > @ncell_cutoff")
        .query("dataset != 'alzheimer'")["cor_peak_significant"]
        .mean()
    )
    print(ncell_cutoff, score)

# %%
ncell_cutoff = 100

scores_joined.query("enricher == 'cluster_vs_background'").query(
    "n_cells > @ncell_cutoff"
).query("slope_logodds_all > 0").groupby(["dataset", "peakcaller", "diffexp"])[
    "logslope_logodds_all"
].mean().unstack(
    "dataset"
).plot(
    kind="bar", lw=0
)

# %%
scores_joined.query("enricher == 'cluster_vs_clusters'").query("n_cells > 0").groupby(
    ["dataset", "peakcaller", "diffexp"]
)["cor_diff_significant"].mean().unstack("dataset").plot(kind="bar", lw=0)

# %% [markdown]
# ## Plot

# %% [markdown]
# ### All methods, datasets and metrics and datasets

# %%
datasets_info = pd.DataFrame(
    index=design.groupby(["dataset", "promoter", "latent"]).first().index
)
datasets_info["label"] = datasets_info.index.get_level_values("dataset")
datasets_info["ix"] = np.arange(len(datasets_info))

# %%
methods_info = chdm.methods.peakcaller_diffexp_combinations.query(
    "peakcaller != 'gene_body'"
).copy()
methods_info["ix"] = -np.arange(len(methods_info))

# %%
group_ids = [
    *methods_info.index.names,
    *datasets_info.index.names,
]

ncell_cutoff = 0
average_n_positions_cutoff = 10**4
meanscores = pd.concat(
    [
        scores_joined.query("enricher == 'cluster_vs_clusters'")
        .query("n_cells > @ncell_cutoff")
        .query("average_n_positions > @average_n_positions_cutoff")
        .groupby(group_ids)["logodds_difference_significant"]
        .mean()
        .to_frame(),
        scores_joined.query("enricher == 'cluster_vs_clusters'")
        .query("n_cells > @ncell_cutoff")
        .query("average_n_positions > @average_n_positions_cutoff")
        .groupby(group_ids)["cor_diff_significant"]
        .mean(),
        scores_joined.query("enricher == 'cluster_vs_clusters'")
        .query("n_cells > @ncell_cutoff")
        .query("average_n_positions > @average_n_positions_cutoff")
        .groupby(group_ids)["cor_diff_all"]
        .mean(),
        scores_joined.query("enricher == 'cluster_vs_background'")
        .query("(n_cells > @ncell_cutoff)")
        .query("average_n_positions > @average_n_positions_cutoff")
        .query("slope_logodds_all > 0")
        .groupby(group_ids)["logslope_logodds_all"]
        .mean(),
    ],
    axis=1,
)

meanscores["cor_diff_significant_logratio"] = np.log(
    1
    + meanscores["cor_diff_significant"]
    / scores_joined.query("enricher == 'cluster_vs_clusters'")[
        "cor_peak_significant"
    ].mean()
)

# %%
(
    np.exp(
        meanscores.query("dataset not in ['alzheimer']").groupby("peakcaller").mean()
    )
).style.bar()

# %%
np.exp(meanscores.groupby(["dataset"]).mean().mean())

# %%
metrics_info = pd.DataFrame(
    [
        {
            "label": "$\\Delta$ cor\n(ChromatinHD\n-method)",
            "metric": "cor_diff_significant",
            "limits": (-0.1, 0.1),
            "transform": lambda x: x,
        },
        {
            "label": "cor ratio\n(ChromatinHD\n/method)",
            "metric": "cor_diff_significant_logratio",
            "limits": (np.log(1 / 2), np.log(2)),
            "ticks": [-np.log(2), 0, np.log(2)],
            "ticklabels": ["½", "1", "2"],
            "transform": lambda x: x,
        },
        # {
        #     "label": r"$\Delta$ log-odds",
        #     "metric": "logodds_difference_significant",
        #     "limits": (np.log(1 / 1.5), np.log(1.5)),
        #     "ticks": [-0.5, 0, 0.5],
        #     "ticklabels": ["-0.5", "0", "+0.5"],
        # },
        # {
        #     "label": r"Slope logodds",
        #     "metric": "logslope_logodds_all",
        #     "limits": (np.log(1 / 2), np.log(2)),
        #     "ticks": [np.log(1 / 2), 0, np.log(2)],
        #     "ticklabels": ["½", "1", "2"],
        #     "transform": lambda x: x,
        # },
    ]
).set_index("metric")
metrics_info["ix"] = np.arange(len(metrics_info))
metrics_info["ticks"] = metrics_info["ticks"].fillna(
    metrics_info.apply(
        lambda metric_info: [metric_info["limits"][0], 0, metric_info["limits"][1]],
        axis=1,
    )
)
metrics_info["ticklabels"] = metrics_info["ticklabels"].fillna(
    metrics_info.apply(lambda metric_info: metric_info["ticks"], axis=1)
)

# %%
panel_width = 6 / 4
panel_resolution = 1 / 4

fig, axes = plt.subplots(
    len(metrics_info),
    len(datasets_info),
    figsize=(
        len(datasets_info) * panel_width,
        len(metrics_info) * len(methods_info) * panel_resolution,
    ),
    gridspec_kw={"wspace": 0.05, "hspace": 0.2},
    squeeze=False,
)

for dataset, dataset_info in datasets_info.iterrows():
    axes_dataset = axes[:, dataset_info["ix"]].tolist()
    for metric, metric_info in metrics_info.iterrows():
        ax = axes_dataset.pop(0)
        ax.set_xlim(metric_info["limits"])
        plotdata = (
            pd.DataFrame(
                index=pd.MultiIndex.from_tuples(
                    [dataset], names=datasets_info.index.names
                )
            )
            .join(meanscores)
            .reset_index()
        )
        plotdata = pd.merge(
            plotdata,
            methods_info,
            on=methods_info.index.names,
        )

        ax.barh(
            width=plotdata[metric],
            y=plotdata["ix"],
            color=plotdata["color"],
            lw=0,
            zorder=0,
        )
        ax.set_xticks([])
        ax.set_yticks([])

        # out of limits values
        metric_limits = metric_info["limits"]
        plotdata_annotate = plotdata.loc[
            (plotdata[metric] < metric_limits[0])
            | (plotdata[metric] > metric_limits[1])
        ]
        transform = mpl.transforms.blended_transform_factory(ax.transAxes, ax.transData)
        metric_transform = metric_info.get("transform", lambda x: x)
        for _, plotdata_row in plotdata_annotate.iterrows():
            left = plotdata_row[metric] < metric_limits[0]
            ax.text(
                x=0.03 if left else 0.97,
                y=plotdata_row["ix"],
                s=f"{metric_transform(plotdata_row[metric]):+.2f}",
                transform=transform,
                va="center",
                ha="left" if left else "right",
                color="#FFFFFFCC",
                fontsize=6,
            )

# Datasets
for dataset, dataset_info in datasets_info.iterrows():
    ax = axes[0, dataset_info["ix"]]
    ax.set_title(dataset_info["label"], fontsize=8)

# Metrics
for metric, metric_info in metrics_info.iterrows():
    ax = axes[metric_info["ix"], 0]
    ax.set_xticks(metric_info["ticks"])
    ax.set_xticklabels(metric_info["ticklabels"])

    ax = axes[metric_info["ix"], 1]
    ax.set_xlabel(metric_info["label"])

# Methods
for ax in axes[:, 0]:
    ax.set_yticks(methods_info["ix"])
    ax.set_yticklabels(methods_info["label"])

for ax in axes.flatten():
    ax.set_ylim(methods_info["ix"].min() - 0.5, 0.5)

manuscript.save_figure(fig, "2", "likelihood_all_scores_datasets")

# %% [markdown]
# ### Averaged over all datasets

# %%
group_ids = [*methods_info.index.names]

ncell_cutoff = 0
average_n_positions_cutoff = 10**4
meanscores = pd.concat(
    [
        scores_joined.query("enricher == 'cluster_vs_clusters'")
        .query("n_cells > @ncell_cutoff")
        .query("average_n_positions > @average_n_positions_cutoff")
        .groupby(group_ids)["cor_diff_significant"]
        .mean(),
        # scores_joined.query("enricher == 'cluster_vs_clusters'").query("n_cells > @ncell_cutoff").query("average_n_positions > @average_n_positions_cutoff").groupby(group_ids)["cor_diff_all"].mean(),
        scores_joined.query("enricher == 'cluster_vs_clusters'")
        .query("n_cells > @ncell_cutoff")
        .query("average_n_positions > @average_n_positions_cutoff")
        .groupby(group_ids)["logodds_difference_significant"]
        .mean()
        .to_frame(),
        # scores_joined.query("enricher == 'cluster_vs_clusters'").query("(n_cells > @ncell_cutoff)").query("average_n_positions > @average_n_positions_cutoff").groupby(group_ids)["cor_diff_significant_logratio"].mean(),
        scores_joined.query("enricher == 'cluster_vs_background'")
        .query("(n_cells > @ncell_cutoff)")
        .query("average_n_positions > @average_n_positions_cutoff")
        .query("slope_logodds_all > 0")
        .groupby(group_ids)["logslope_logodds_all"]
        .mean(),
    ],
    axis=1,
)

meanscores["cor_diff_significant_logratio"] = np.log(
    1
    + meanscores["cor_diff_significant"]
    / scores_joined.query("enricher == 'cluster_vs_clusters'")[
        "cor_peak_significant"
    ].mean()
)

# %%
panel_width = 5 / 4
panel_resolution = 1 / 8

fig, axes = plt.subplots(
    1,
    len(metrics_info),
    figsize=(
        len(metrics_info) * panel_width,
        len(methods_info) * panel_resolution,
    ),
    gridspec_kw={"wspace": 0.2},
    squeeze=False,
)

for metric_ix, (metric, metric_info) in enumerate(metrics_info.iterrows()):
    ax = axes[0, metric_ix]
    ax.set_xlim(metric_info["limits"])
    plotdata = meanscores.reset_index()
    plotdata = pd.merge(
        plotdata,
        methods_info,
        on=methods_info.index.names,
    )

    ax.barh(
        width=plotdata[metric],
        y=plotdata["ix"],
        color=plotdata["color"],
        lw=0,
        zorder=0,
    )
    ax.set_xticks([])
    ax.set_yticks([])

    # out of limits values
    metric_limits = metric_info["limits"]
    plotdata_annotate = plotdata.loc[
        (plotdata[metric] < metric_limits[0]) | (plotdata[metric] > metric_limits[1])
    ]
    transform = mpl.transforms.blended_transform_factory(ax.transAxes, ax.transData)
    metric_transform = metric_info.get("transform", lambda x: x)
    for _, plotdata_row in plotdata_annotate.iterrows():
        left = plotdata_row[metric] < metric_limits[0]
        ax.text(
            x=0.03 if left else 0.97,
            y=plotdata_row["ix"],
            s=f"{metric_transform(plotdata_row[metric]):+.2f}",
            transform=transform,
            va="center",
            ha="left" if left else "right",
            color="#FFFFFFCC",
            fontsize=6,
        )

# Metrics
for metric, metric_info in metrics_info.iterrows():
    ax = axes[0, metric_info["ix"]]
    ax.set_xticks(metric_info["ticks"])
    ax.set_xticklabels(metric_info["ticklabels"])
    ax.set_xlabel(metric_info["label"])
    ax.axvline(0, color="#000000", lw=0.5, zorder=0, dashes=(2, 2))

# Methods
ax = axes[0, 0]
ax.set_yticks(methods_info["ix"])
ax.set_yticklabels(methods_info["label"], fontsize=8)

for ax in axes.flatten():
    ax.set_ylim(methods_info["ix"].min() - 0.5, 0.5)

manuscript.save_figure(fig, "2", "likelihood_all_scores")

# %% [markdown]
# ## Example

# Find good examples

# %%
scores_joined.query("dataset == 'lymphoma'")["peakcaller"].unique()

# %%
(
    scores_joined.query(
        "(promoter == '10k10k') and (diffexp == 'scanpy') and (enricher == 'cluster_vs_clusters')"
    )
    .query("peakcaller == 'macs2_leiden_0.1'")
    # .query("dataset == 'lymphoma'")
    .query("n_cells > 100")[
        [
            "dataset",
            "cor_diff_significant",
            "cor_peak_significant",
            "cor_region_significant",
            "cluster",
        ]
    ]
    .dropna()
    .sort_values("cor_diff_significant")
)


# %%

# %%
