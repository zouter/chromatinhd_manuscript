# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.11.3
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% tags=[]
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
import tempfile
import requests

# %% tags=[]
data_folder = chd.get_output() / "data" / "eqtl" / "onek1k"
raw_data_folder = data_folder / "raw"

# %% [markdown]
# ## Run for all

# %% tags=[]
cluster_info = pd.DataFrame(
    {"cluster": pd.Series(adata2.obs["cluster"].unique()).sort_values().dropna()}
).set_index("cluster")
cluster_info["ix"] = np.arange(len(cluster_info))
cluster_to_cluster_ix = cluster_info["ix"].to_dict()

genes["ix"] = np.arange(len(genes))
gene_to_gene_ix = genes["ix"].to_dict()

variants_info["ix"] = np.arange(len(variants_info))
variant_to_variant_ix = variants_info["ix"].to_dict()

donor_info = samples.set_index("donor")


# %% tags=[]
def get_types(window):
    # f"{gene_oi.chr}:{window[0]}-{window[1]}"
    # get types
    types = []
    variant_ids = []
    for variant in vcf(window):
        types.append(
            variant.gt_types.copy()
        )  #! Copy is important due to repurposing of gt_types by cyvcf2
        variant_ids.append(variant.ID)
    types = np.stack(types, -1)
    types[types == 2] = 1
    types[types == 3] = 2
    return types, variant_ids


def get_expression(gene_id):
    expression = sc.get.obs_df(adata2, gene_oi.name)
    expression.index = pd.MultiIndex.from_frame(adata2.obs[["cluster", "donor"]])
    expression = expression.unstack().T
    expression.index = samples.set_index("donor")["old"].values
    expression = expression.reindex(vcf.samples)
    return expression


# %% tags=[]
# genes_oi = genes.iloc[:1000]
genes_oi = genes.query("symbol == 'CTLA4'")

# %% tags=[]
data = {"p": [], "cluster_ix": [], "slope": [], "variant_ix": [], "gene_ix": []}
for _, gene_oi in tqdm.tqdm(genes_oi.iterrows(), total=len(genes_oi)):
    window_size = 10**6
    window = (gene_oi["tss"] - window_size, gene_oi["tss"] + window_size)

    # get types
    window_str = f"{gene_oi.chr}:{window[0]}-{window[1]}"
    types, variant_ids = get_types(window_str)

    gene_ix = gene_to_gene_ix[gene_oi.name]

    # get expression
    expression = get_expression(gene_oi.name)

    X = types[:, None, :]
    Y = expression.values.copy()[:, :, None]
    Y[np.isnan(Y)] = 0.0

    # slope, p = chd.qtl.mapping.calculate_pearson_univariate_multiinput_multioutput(X, Y)
    slope, p = chd.qtl.mapping.calculate_spearman_univariate_multiinput_multioutput(
        X, Y
    )

    data["p"].append(p.flatten())
    data["slope"].append(slope.flatten())
    data["cluster_ix"].append(np.repeat(cluster_info["ix"].values, len(variant_ids)))
    data["variant_ix"].append(
        np.tile(variants_info.loc[variant_ids]["ix"].values, len(cluster_info))
    )
    data["gene_ix"].append(
        np.repeat(gene_oi["ix"], len(cluster_info) * len(variant_ids))
    )

# scores = pd.DataFrame(scores)

# %% tags=[]
scores = pd.DataFrame({k: np.concatenate(v) for k, v in data.items()})

# %% tags=[]
scores["cluster"] = pd.Categorical.from_codes(
    scores["cluster_ix"], categories=cluster_info.index
)
scores["variant"] = pd.Categorical.from_codes(
    scores["variant_ix"], categories=variants_info.index
)
scores["gene"] = pd.Categorical.from_codes(scores["gene_ix"], categories=genes.index)

# %% tags=[]
scores = scores.dropna(subset=["p"]).copy()

# %% tags=[]
import statsmodels.stats.multitest

scores["q"] = statsmodels.stats.multitest.fdrcorrection(scores["p"])[1]
scores["log10q"] = np.log10(scores["q"])

# %% tags=[]
scores["variant_rsid"] = pd.Categorical(
    variants_info["rsid"].iloc[scores["variant_ix"]]
)

# %% tags=[]
scores["significant"] = scores["q"] < 0.05

# %% tags=[]
scores.groupby("cluster")["significant"].sum().plot(kind="bar")

# %% tags=[]
scores.sort_values("p")

# %% tags=[]
import torch

# %% tags=[]
X

# %% [markdown]
# ### Interpret

# %% tags=[]
scores["significant"] = scores["q"] < 0.05

# %% tags=[]
scores.groupby("cluster")["significant"].sum()

# %% tags=[]
score_oi = scores.query("(q < 0.05) & (cluster == 'NK')").sort_values("q").iloc[10]
gene_oi = genes.loc[score_oi["gene"]]
variant_info = variants_info.loc[score_oi["variant"]]

scores.query("(variant == @variant_info.name) & (gene == @gene_oi.name)").head(
    10
).style.bar(subset=["slope"])

# %% tags=[]
expression = get_expression(gene_oi.name)

# %% tags=[]
variant = list(vcf(f"{variant_info.chr}:{variant_info.start}-{variant_info.end}"))[0]

expression_clusters = {}
for cluster in expression.columns:
    expression_cluster = expression[cluster]
    samples_profiled = ~pd.isnull(expression_cluster)

    expression_clusters[cluster] = [expression_cluster.values, samples_profiled]

plotdata = []

for cluster, (y_all, samples_profiled) in expression_clusters.items():
    gt = pd.Categorical(
        np.array(["ref/ref", "alt/ref", "-", "alt/alt"])[variant.gt_types],
        categories=["ref/ref", "alt/ref", "alt/alt"],
    )
    plotdata.append(
        pd.DataFrame({"genotype": gt, "expression": y_all, "cluster": cluster})
    )
plotdata = pd.concat(plotdata)

# %% tags=[]
plotdata = plotdata.dropna()

# %% tags=[]
sns.boxplot(data=plotdata, x="cluster", y="expression", hue="genotype")

# %% tags=[]
sc.pl.pca(adata2, color=["cluster", gene_oi.name])

# %% tags=[]
cluster = "Monocytes"
cluster = "CD4 T"
scores_oi = scores.query("cluster == @cluster").join(variants_info, on="variant")

# %% tags=[]
fig, ax = plt.subplots()
ax.scatter(scores_oi["pos"], -scores_oi["log10q"])
ax.axhline(-np.log10(0.05))

# %% tags=[]
fig, ax = plt.subplots()
ax.scatter(scores_oi["pos"], scores_oi["r"], c=scores_oi["log10q"])

# %% tags=[]
cluster_1 = "CD4 T"
cluster_2 = "CD8 T"  # IRF7
cluster_1 = "Monocytes"
cluster_2 = "B"  # RGS1
cluster_1 = "CD4 T"
cluster_2 = "CD8 T"  # XBP1

scores_oi_1 = scores.query("cluster == @cluster_1").join(variants_info, on="variant")
scores_oi_2 = scores.query("cluster == @cluster_2").join(variants_info, on="variant")

# %% tags=[]
fig, ax = plt.subplots()
ax.scatter(-scores_oi_1["log10q"], -scores_oi_2["log10q"], c=scores_oi_1["r"])

# %%

# %%
