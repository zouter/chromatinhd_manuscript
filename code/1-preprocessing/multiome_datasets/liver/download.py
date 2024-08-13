# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.7
#   kernelspec:
#     display_name: chromatinhd
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

import torch

import pickle

import scanpy as sc

import tqdm.auto as tqdm
import io

# %%
import chromatinhd as chd

# %%
folder_root = chd.get_output()
folder_data = folder_root / "data"

dataset_name = "liver"
main_url = "https://cf.10xgenomics.com/samples/cell-arc/2.0.0/pbmc_granulocyte_sorted_10k/pbmc_granulocyte_sorted_10k"
genome = "mm10"
organism = "mm"

folder_data_preproc = folder_data / dataset_name
folder_data_preproc.mkdir(exist_ok=True, parents=True)

folder_dataset = chd.get_output() / "datasets" / dataset_name

# %% [markdown]
# ## Download

# %%
# ! wget https://ftp.ncbi.nlm.nih.gov/geo/series/GSE218nnn/GSE218468/suppl/GSE218468_TEW_043783_523d9c_Multiome_Liver_10xprotocol_fragments.tsv.gz -O {folder_data_preproc}/atac_fragments.tsv.gz.raw

# %%
# # !zcat {folder_data_preproc}/atac_fragments.tsv.gz > {folder_data_preproc}/atac_fragments.tsv

if not (folder_data_preproc/"atac_fragments.tsv.gz").exists():
    import pysam
    pysam.tabix_compress(str(folder_data_preproc/"atac_fragments.tsv.gz.raw"), str(folder_data_preproc/"atac_fragments.tsv.gz"), force=True)
    pysam.tabix_index(str(folder_data_preproc/"atac_fragments.tsv.gz"), seq_col = 0, start_col = 1, end_col = 2)

# %%
# !wget https://ftp.ncbi.nlm.nih.gov/geo/series/GSE218nnn/GSE218468/suppl/GSE218468_multiome_rna_counts.tsv.gz -O {folder_data_preproc}/rna_counts.tsv.gz

# %% [markdown]
# ## Create transcriptome

# %%
transcriptome = chd.data.Transcriptome(folder_dataset / "transcriptome")

# %%
counts = pd.read_table(folder_data_preproc / "rna_counts.tsv.gz", index_col=0, sep = "\t").T

# %%
obs = pd.DataFrame({"cell":counts.index}).set_index("cell")
var = pd.DataFrame({"symbol":counts.columns})
mapping = chd.biomart.map_symbols(chd.biomart.Dataset.from_genome(genome), adata.var.index).groupby("external_gene_name").first().reindex(var["symbol"])
mapping["ix"] = np.arange(len(mapping))
mapping = mapping.dropna()
var = var.loc[var["symbol"].isin(mapping.index)]
var.index = pd.Series(mapping["ensembl_gene_id"], name = "gene")
counts = counts.loc[:,var["symbol"]]

# %%
import scipy.sparse
adata = sc.AnnData(scipy.sparse.csr_matrix(counts.values), obs = obs, var = var)

# %%
transcripts = chd.biomart.get_transcripts(chd.biomart.Dataset.from_genome(genome), gene_ids=adata.var.index.unique())
pickle.dump(transcripts, (folder_data_preproc / 'transcripts.pkl').open("wb"))

# %%
# only retain genes that have at least one ensembl transcript
adata = adata[:, adata.var.index.isin(transcripts["ensembl_gene_id"])]

# %%
sc.external.pp.scrublet(adata)

# %%
adata.obs["doublet_score"].plot(kind="hist")

# %%
adata.obs["doublet"] = (adata.obs["doublet_score"] > 0.1).astype("category")

print(adata.obs.shape[0])
adata = adata[~adata.obs["doublet"].astype(bool)]
print(adata.obs.shape[0])

# %%
size_factor = np.median(np.array(adata.X.sum(1)))
adata.uns["size_factor"] = size_factor

# %%
adata.raw = adata

# %%
sc.pp.normalize_total(adata, size_factor)
sc.pp.log1p(adata)
sc.pp.pca(adata)
sc.pp.highly_variable_genes(adata)

sc.pp.neighbors(adata)
sc.tl.umap(adata)

# %%
adata.layers["normalized"] = adata.X
adata.layers["counts"] = adata.raw.X

# %%
import magic

magic_operator = magic.MAGIC(knn=30, solver = "approximate")
X_smoothened = magic_operator.fit_transform(adata.X)
adata.layers["magic"] = X_smoothened

# %%
import pickle
pickle.dump(adata, (folder_data_preproc / 'adata.pkl').open("wb"))

# %% [markdown]
# ## Interpret and subset

# %%
adata = pickle.load((folder_data_preproc / 'adata.pkl').open("rb"))

# %%
sc.tl.leiden(adata, resolution=1.0)
sc.pl.umap(adata, color="leiden")

# %%
sc.tl.rank_genes_groups(adata, "leiden", method="wilcoxon", key_added  = "wilcoxon", use_raw = False)
# genes_oi = sc.get.rank_genes_groups_df(adata, group=None, key='rank_genes_groups').sort_values("scores", ascending = False).groupby("group").head(2)["names"]

# %%
diffexp = sc.get.rank_genes_groups_df(adata, group=None, key='wilcoxon').sort_values("scores", ascending = False).groupby("group").head(5)
diffexp["symbol"] = diffexp["names"].apply(lambda x: adata.var.loc[x, "symbol"])
diffexp.set_index("group").loc["10"]

# %%
import io
marker_annotation = pd.read_table(
    io.StringIO(
        """ix	symbols	celltype
0	Alb, Aox3, Cyp2f2	Portal Hepatocyte
0	Sult2a8	Mid Hepatocyte
0	Slc1a2, Glul	Central Hepatocyte
0	Ptprb, Stab2	LSEC
1	Clec4f	KC
1	Rbms3	Stellate
1	Pkhd1	Cholangiocyte
1	Ptprc	Immune
"""
    )
).set_index("celltype")
marker_annotation["symbols"] = marker_annotation["symbols"].str.split(", ")

# %%
import chromatinhd.utils.scanpy
cluster_celltypes = chd.utils.scanpy.evaluate_partition(
    adata, marker_annotation["symbols"].to_dict(), "symbol", partition_key="leiden"
).idxmax()

adata.obs["celltype"] = adata.obs["celltype"] = cluster_celltypes[
    adata.obs["leiden"]
].values
adata.obs["celltype"] = adata.obs["celltype"] = adata.obs[
    "celltype"
].astype(str)

# %%
sc.pl.umap(adata, color=["celltype", "leiden"], legend_loc="on data")

# %%
pickle.dump(adata, (folder_data_preproc / 'adata_annotated.pkl').open("wb"))

# %% [markdown]
# ## TSS

# %%
adata = pickle.load((folder_data_preproc / 'adata_annotated.pkl').open("rb"))

# %%
transcripts = pickle.load((folder_data_preproc / 'transcripts.pkl').open("rb"))
transcripts = transcripts.loc[transcripts["ensembl_gene_id"].isin(adata.var.index)]

# %%
fragments_file = folder_data_preproc / "atac_fragments.tsv.gz"
selected_transcripts = chd.data.regions.select_tss_from_fragments(transcripts, fragments_file)

# %%
np.log(transcripts.groupby("ensembl_gene_id")["n_fragments"].max()).shape

# %%
plt.scatter(adata.var["means"], np.log(transcripts.groupby("ensembl_gene_id")["n_fragments"].max())[adata.var.index])
np.corrcoef(adata.var["means"], np.log(transcripts.groupby("ensembl_gene_id")["n_fragments"].max() + 1)[adata.var.index])

# %%
pickle.dump(selected_transcripts, (folder_data_preproc / 'selected_transcripts.pkl').open("wb"))

# %% [markdown]
# ## Preprocess

# %%
dataset_folder = chd.get_output() / "datasets" / dataset_name
dataset_folder.mkdir(exist_ok=True, parents=True)

# %%
adata = pickle.load((folder_data_preproc / "adata_annotated.pkl").open("rb"))
adata.obs["cell_original"] = adata.obs.index
adata.obs.index = adata.obs.index.str.split("-").str[0] + "-1"

# %% [markdown]
# ### Create transcriptome

# %%
transcriptome = chd.data.transcriptome.Transcriptome.from_adata(adata[:, adata.var.sort_values("dispersions_norm").tail(5000).index], path=dataset_folder / "transcriptome")

# %%
sc.pl.umap(adata, color = adata.var.index[(adata.var["symbol"] == "Glul")][0])

# %% [markdown]
# ### 10k

# %%
selected_transcripts = pickle.load((folder_data_preproc / "selected_transcripts.pkl").open("rb")).loc[transcriptome.var.index]
regions = chd.data.regions.Regions.from_transcripts(
    selected_transcripts, [-10000, 10000], dataset_folder / "regions" / "10k10k"
)

# %%
# # !zcat {folder_data_preproc}/atac_fragments.tsv.gz | head -n 1000

# %%
fragments_file = folder_data_preproc / "atac_fragments.tsv.gz"
fragments = chd.data.Fragments(dataset_folder / "fragments" / "10k10k")

fragments.regions = regions
fragments = chd.data.Fragments.from_fragments_tsv(
    fragments_file=fragments_file,
    regions=regions,
    obs=transcriptome.obs,
    path=fragments.path,
    overwrite = True
)

# %%
fragments.create_regionxcell_indptr()

# %% [markdown]
# ### 100k

# %%
selected_transcripts = pickle.load((folder_data_preproc / "selected_transcripts.pkl").open("rb")).loc[transcriptome.var.index]
regions = chd.data.regions.Regions.from_transcripts(
    selected_transcripts, [-100000, 100000], dataset_folder / "regions" / "100k100k"
)

# %%
fragments_file = folder_data_preproc / "atac_fragments.tsv.gz"
fragments = chd.data.Fragments(dataset_folder / "fragments" / "100k100k")
fragments.regions = regions
fragments = chd.data.Fragments.from_fragments_tsv(
    fragments_file=fragments_file,
    regions=regions,
    obs=transcriptome.obs,
    path=fragments.path,
    overwrite = True,
)

# %%
fragments.create_regionxcell_indptr()
