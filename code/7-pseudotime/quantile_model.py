#%%
import IPython
if IPython.get_ipython() is not None:
    IPython.get_ipython().magic('load_ext autoreload')
    IPython.get_ipython().magic('autoreload 2')

import gc
import torch
import torch_scatter
import pickle
import pathlib
import tempfile
import scipy.stats
import numpy as np
import pandas as pd
import scanpy as sc
import tqdm.auto as tqdm

import chromatinhd as chd
import chromatinhd.loaders.fragments
import chromatinhd.models.likelihood.v9 as vae_model

import plotly.express as px
import matplotlib.pyplot as plt
import matplotlib as mpl
import seaborn as sns
sns.set_style('ticks')
# %config InlineBackend.figure_format='retina'

# %%
folder_root = chd.get_output()
folder_data = folder_root / "data"
dataset_name = "hspc"
folder_data_preproc = folder_data / dataset_name

# %%
promoter_name, window = "10k10k", np.array([-10000, 10000])
promoters = pd.read_csv(folder_data_preproc / ("promoters_" + promoter_name + ".csv"), index_col = 0)
folds = pd.read_pickle(folder_data_preproc / "fragments_myeloid" / promoter_name / "folds.pkl")
fragments = chd.data.Fragments(folder_data_preproc / "fragments_myeloid" / promoter_name)
fragments.window = window

cells_train = folds[0]['cells_train']
cells_validation = folds[0]['cells_validation']

# %% 
# ## Create loaders

n_cells_step = 100
n_genes_step = 50

loaders_train = chromatinhd.loaders.pool.LoaderPool(
    chromatinhd.loaders.fragments.Fragments,
    {"fragments": fragments, "cellxgene_batch_size": n_cells_step * n_genes_step},
    n_workers = 20,
    shuffle_on_iter = True
)

minibatches_train = chd.loaders.minibatching.create_bins_random(
    cells_train,
    np.arange(fragments.n_genes),
    fragments.n_genes,
    n_genes_step = n_genes_step,
    n_cells_step = n_cells_step,
    use_all = True,
    permute_genes = False
)

loaders_train.initialize(minibatches_train)

loaders_validation = chromatinhd.loaders.pool.LoaderPool(
    chromatinhd.loaders.fragments.Fragments,
    {"fragments": fragments, "cellxgene_batch_size": n_cells_step * n_genes_step},
    n_workers = 5
)

minibatches_validation = chd.loaders.minibatching.create_bins_random(
    cells_validation,
    np.arange(fragments.n_genes),
    fragments.n_genes,
    n_genes_step = n_genes_step,
    n_cells_step = n_cells_step,
    use_all = True,
    permute_genes = False
)

loaders_validation.initialize(minibatches_validation)

# %%
# ## Model
# ### Load latent space

# %%
# loading
latent_name = "latent_time"
latent_folder = folder_data_preproc / "latent"
df = pd.read_csv(folder_data_preproc / "MV2_latent_time_myeloid.csv", index_col = 0)
df['quantile'] = pd.qcut(df['latent_time'], q=10, labels=False)
fragments.obs["cluster"] = df['quantile']

latent = pd.get_dummies(df['quantile'], prefix='quantile')
latent_torch = torch.from_numpy(latent.values).to(torch.float)
n_latent_dimensions = latent.shape[-1]

cluster_info = pd.DataFrame()
cluster_info['cluster'] = list(latent.columns)
cluster_info['label'] = list(latent.columns)
cluster_info['dimension'] = range(n_latent_dimensions)
cluster_info["color"] = sns.color_palette("husl", latent.shape[1])
cluster_info.set_index('cluster', inplace=True)

# TODO move this to separate script
# latent_name = "celltype"
# latent_folder = folder_data_preproc / "latent"
# latent = pickle.load((latent_folder / (latent_name + ".pkl")).open("rb"))
# latent_torch = torch.from_numpy(latent.values).to(torch.float)
# n_latent_dimensions = latent.shape[-1]

# cluster_info = pd.read_pickle(latent_folder / (latent_name + "_info.pkl"))
# cluster_info["color"] = sns.color_palette("husl", latent.shape[1])
# fragments.obs["cluster"] = pd.Categorical(pd.from_dummies(latent).iloc[:, 0])

# %%
# ### Create model
reflatent = torch.eye(n_latent_dimensions).to(torch.float)
reflatent_idx = torch.from_numpy(np.where(latent.values)[1])

# %%
model = vae_model.Decoding(fragments, torch.from_numpy(latent.values), nbins = (128, 64, 32, ))

# %% [markdown]
# ### Prior distribution

# %%
device = "cuda"
model = model.to(device)

# %%
fragments.create_cut_data()

# %%
gene_oi = 0

# %%
model.n_genes = fragments.n_genes

# %%
bc = torch.bincount(fragments.genemapping)

# %%
model = model.to(device)

#%%
def plot_distribution(latent, latent_torch, cluster_info, fragments, transcriptome, gene_oi, model, device, prior = True):
    fig, axes = plt.subplots(latent.shape[1], 1, figsize=(20, 1*latent.shape[1]), sharex = True, sharey = True)

    probs = []
    pseudocoordinates = torch.linspace(0, 1, 1000).to(device)
    bins = np.linspace(0, 1, 500)
    binmids = (bins[1:] + bins[:-1])/2
    binsize = binmids[1] - binmids[0]
    fragments_oi_all = (fragments.cut_local_gene_ix == gene_oi)

    gene_id = transcriptome.var.index[gene_oi]

    for i, ax in zip(range(latent.shape[1]), axes):
        lib_all = model.libsize.cpu().numpy()
        
        cells_oi = torch.where(latent_torch[:, i])[0]
        lib_oi = model.libsize[cells_oi].cpu().numpy()
        n_cells = latent_torch[:, i].sum()
        
        color = cluster_info.iloc[i]["color"]
        fragments_oi = (latent_torch[fragments.cut_local_cell_ix, i] != 0) & (fragments.cut_local_gene_ix == gene_oi)
        
        bincounts, _ = np.histogram(fragments.cut_coordinates[fragments_oi].cpu().numpy(), bins = bins)
        ax.bar(binmids, bincounts / n_cells * len(bins), width = binsize, color = "#888888", lw = 0)

        # Plot initial posterior distribution
        pseudolatent = torch.zeros((len(pseudocoordinates), latent.shape[1])).to(device)
        pseudolatent[:, i] = 1.
        
        prob = model.evaluate_pseudo(pseudocoordinates.to(device), latent = pseudolatent.to(device), gene_oi = gene_oi)
        ax.plot(pseudocoordinates.cpu().numpy(), np.exp(prob), label = i, color = color, lw = 2, zorder = 20)
        ax.plot(pseudocoordinates.cpu().numpy(), np.exp(prob), label = i, color = "#FFFFFFFF", lw = 3, zorder = 10)
        
        ax.set_ylabel(f"{cluster_info.iloc[i]['label']}\n freq={fragments_oi.sum()/n_cells}", rotation = 0, ha = "right", va = "center")
        ax.set_ylim(0, 40)
        
        probs.append(prob)

    suffix = "_prior" if prior else ""
    plt.savefig(folder_data_preproc / ("plots/evaluate_pseudo" + suffix) / (str(gene_oi) + ".pdf"))
    probs = np.stack(probs)
    return probs

#%%
probs = plot_distribution(latent, latent_torch, cluster_info, fragments, gene_oi, model, device, prior=True)

# %%
def plot_delta_heights(latent, latent_torch, cluster_info, fragments, gene_oi, model, device):
    pass

main = chd.grid.Grid(padding_height=0.1)
fig = chd.grid.Figure(main)

nbins = np.array(model.mixture.transform.nbins)
bincuts = np.concatenate([[0], np.cumsum(nbins)])
binmids = bincuts[:-1] + nbins/2

ax = main[0, 0] = chd.grid.Ax((10, 0.25))
ax = ax.ax
plotdata = (model.mixture.transform.unnormalized_heights.data.cpu().numpy())[[gene_oi]]
ax.imshow(plotdata, aspect = "auto")
ax.set_yticks([])
for b in bincuts:
    ax.axvline(b-0.5, color = "black", lw = 0.5)
ax.set_xlim(0-0.5, plotdata.shape[1]-0.5)
ax.set_xticks([])
ax.set_ylabel("$h_0$", rotation = 0, ha = "right", va = "center")

ax = main[1, 0] = chd.grid.Ax(dim = (10, n_latent_dimensions * 0.25))
ax = ax.ax
plotdata = (model.decoder.logit_weight.data[gene_oi].cpu().numpy())
ax.imshow(plotdata, aspect = "auto", cmap = mpl.cm.RdBu_r, vmax = np.log(2), vmin = np.log(1/2))
ax.set_yticks(range(len(cluster_info)))
ax.set_yticklabels(cluster_info.index, rotation = 0, ha = "right")
for b in bincuts:
    ax.axvline(b-0.5, color = "black", lw = 0.5)
ax.set_xlim(-0.5, plotdata.shape[1]-0.5)

ax.set_xticks(bincuts-0.5, minor = True)
ax.set_xticks(binmids-0.5)
ax.set_xticklabels(nbins)
ax.xaxis.set_tick_params(length = 0)
ax.xaxis.set_tick_params(length = 5, which = "minor")
ax.set_ylabel("$\Delta h$", rotation = 0, ha = "right", va = "center")

ax.set_xlabel("Resolution")

fig.plot()

# %%
# ### Train
device = "cuda"

# %%
optimizer = chd.optim.SparseDenseAdam(model.parameters_sparse(), model.parameters_dense(autoextend=True), lr = 1e-2)

# %%
loaders_train.restart()
loaders_validation.restart()

gc.collect()
torch.cuda.empty_cache()

# %%
class GeneLikelihoodHook():
    def __init__(self, n_genes):
        self.n_genes = n_genes
        self.likelihood_mixture = []
        self.likelihood_counts = []
        
    def start(self):
        self.likelihood_mixture_checkpoint = np.zeros(self.n_genes)
        self.likelihood_counts_checkpoint = np.zeros(self.n_genes)
        return {}
        
    def run_individual(self, model, data):
        self.likelihood_mixture_checkpoint[data.genes_oi] += torch_scatter.scatter_sum(model.track["likelihood"], data.cut_local_gene_ix, dim_size = data.n_genes).detach().cpu().numpy()
        
    def finish(self):
        self.likelihood_mixture.append(self.likelihood_mixture_checkpoint)
        
hook_genelikelihood = GeneLikelihoodHook(fragments.n_genes)
hooks = [hook_genelikelihood]

# %%
model = model.to(device).train()
loaders_train.restart()
loaders_validation.restart()
trainer = chd.train.Trainer(model, loaders_train, loaders_validation, optimizer, n_epochs = 50, checkpoint_every_epoch=1, optimize_every_step = 1, hooks_checkpoint = hooks)
trainer.train()

# %%
likelihood_mixture = pd.DataFrame(np.vstack(hook_genelikelihood.likelihood_mixture), columns = fragments.var.index).T

# %%
scores = (likelihood_mixture.iloc[:, -1] - likelihood_mixture[0]).sort_values().to_frame("lr")

#%%
transcriptome = chromatinhd.data.Transcriptome(folder_data_preproc / "transcriptome")
transcriptome.var.index = transcriptome.var["Accession"]
transcriptome.var.index.name = "gene"

#%%
scores["label"] = transcriptome.var.loc[scores.index]['symbol']

# %%
pickle.dump(model.to("cpu"), open("./model.pkl", "wb"))

# %%
model = pickle.load(open("./model.pkl", "rb"))

# %% [markdown]
# ## Inference single gene
sns.histplot(model.decoder.rho_weight.weight.data.numpy().flatten())

# %%
z = model.decoder.logit_weight.weight.data.numpy().flatten()
sns.histplot(z[:100])

# %%
scipy.stats.laplace.fit(z)

# %%
device = "cuda"
model = model.to(device).eval()

#%%
model = model.to(device)

# %%
for gene_oi in range(100):
    probs = plot_distribution(latent, latent_torch, cluster_info, fragments, transcriptome, gene_oi, model, device, prior=False)

# %%
sns.heatmap(probs, cmap = mpl.cm.RdBu_r)

# %%
probs_diff = probs - probs.mean(0, keepdims = True)

#%%
sns.heatmap(probs_diff, cmap = mpl.cm.RdBu_r, center = 0.)
