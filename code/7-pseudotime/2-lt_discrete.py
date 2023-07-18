#%%
import IPython
if IPython.get_ipython() is not None:
    IPython.get_ipython().magic('load_ext autoreload')
    IPython.get_ipython().magic('autoreload 2')

import os
import gc
import torch
import torch_scatter
import pickle
import numpy as np
import pandas as pd
import tqdm.auto as tqdm

import chromatinhd as chd
import chromatinhd.loaders.fragments
import chromatinhd.models.likelihood.v9 as vae_model

# %%
folder_root = chd.get_output()
folder_data_preproc = folder_root / "data" / "hspc"
dataset_name = "myeloid"
dataset_name_sub = "MV2"
fragment_dir = folder_data_preproc / f"{dataset_name_sub}_fragments_{dataset_name}"
df_latent_file = folder_data_preproc / f"{dataset_name_sub}_latent_time_{dataset_name}.csv"

promoter_name, window = "10k10k", np.array([-10000, 10000])
promoters = pd.read_csv(folder_data_preproc / f"{dataset_name_sub}_promoters_{promoter_name}.csv", index_col = 0)

info_genes_cells = pd.read_csv(folder_data_preproc / "info_genes_cells.csv")
lineage = info_genes_cells[f'lin_{dataset_name}'].dropna().tolist()

# use this to obtain cell types
df_latent = pd.read_csv(df_latent_file, index_col = 0)
df_latent['quantile'] = pd.qcut(df_latent['latent_time'], 10, labels = False) + 1
latent = pd.get_dummies(df_latent['quantile'])
latent_torch = torch.from_numpy(latent.values).to(torch.float)

fragments = chd.data.Fragments(fragment_dir / promoter_name)
fragments.window = window
fragments.create_cut_data()

#%%
folds = pd.read_pickle(fragment_dir / promoter_name / "folds.pkl")
index = 0
cells_train = folds[index]['cells_train']
cells_validation = folds[index]['cells_validation']

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
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

nbins = (128, 64, 32, )
model = vae_model.Decoding(fragments, torch.from_numpy(latent.values), nbins = nbins)
model = model.to(device)
model.n_genes = fragments.n_genes

#%%
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
optimizer = chd.optim.SparseDenseAdam(model.parameters_sparse(), model.parameters_dense(autoextend=True), lr = 1e-2)
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

model_path = folder_data_preproc / f"models/{dataset_name_sub}_{dataset_name}_quantiles_{'_'.join(str(n) for n in nbins)}_fold_{index}.pkl"
pickle.dump(model.to("cpu"), open(model_path, "wb"))

# %%
model_path = folder_data_preproc / f"models/{dataset_name_sub}_{dataset_name}_quantiles_{'_'.join(str(n) for n in nbins)}_fold_{index}.pkl"
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

model = pickle.load(open(model_path, "rb"))
model = model.to(device).eval()
model = model.to(device)

# %%
def evaluate_pseudo_quantile(latent, gene_oi, model, device):
    pseudocoordinates = torch.linspace(0, 1, 1000).to(device)
    probs = []
    for i in range(latent.shape[1]):
        pseudolatent = torch.zeros((len(pseudocoordinates), latent.shape[1])).to(device)
        pseudolatent[:, i] = 1.
        prob = model.evaluate_pseudo(pseudocoordinates.to(device), latent = pseudolatent.to(device), gene_oi = gene_oi)
        probs.append(prob)
    probs = np.stack(probs)
    return probs

dir_csv = folder_data_preproc / f"{dataset_name_sub}_LQ/lq_{dataset_name}_{'_'.join(str(n) for n in nbins)}_fold_{index}"
os.makedirs(dir_csv, exist_ok=True)

pseudocoordinates = torch.linspace(0, 1, 1000).to(device)

for gene_oi in range(len(promoters)):
    print(gene_oi)
    gene_id = fragments.var.index[gene_oi]
    probs = evaluate_pseudo_quantile(latent, gene_oi, model, device)
    probs_df = pd.DataFrame(np.exp(probs), columns = pseudocoordinates.tolist(), index = latent.columns)
    probs_df.to_csv(dir_csv / f"{gene_id}.csv")

print("Done \n")

# %%
