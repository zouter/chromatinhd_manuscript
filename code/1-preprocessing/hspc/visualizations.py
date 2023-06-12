#%%
import os
import torch
import imageio
import numpy as np
import pandas as pd
import chromatinhd as chd

import seaborn as sns
import plotly.express as px
import plotly.graph_objects as go
import matplotlib.pyplot as plt

# %%
# set folder paths
folder_root = chd.get_output()
folder_data = folder_root / "data"
dataset_name = "hspc"
folder_data_preproc = folder_data / dataset_name
promoter_name, window = "10k10k", np.array([-10000, 10000])

# load data
promoters = pd.read_csv(folder_data_preproc / ("promoters_" + promoter_name + ".csv"), index_col = 0)
fragments = chd.data.Fragments(folder_data_preproc / "fragments_myeloid" / promoter_name)
genes = pd.read_csv(folder_data_preproc / "genes.csv", index_col = 0)
info_genes_cells = pd.read_csv(folder_data_preproc / "info_genes_cells.csv")
s_genes = info_genes_cells['s_genes'].dropna().tolist()
g2m_genes = info_genes_cells['g2m_genes'].dropna().tolist()
hspc_marker_genes = info_genes_cells['hspc_marker_genes'].dropna().tolist()
latent_time = pd.read_csv(folder_data_preproc / 'MV2_latent_time_myeloid.csv')
latent_time['rank_raw'] = latent_time['latent_time'].rank()
latent_time['rank'] = latent_time['rank_raw'] / latent_time.shape[0]

# %%
coordinates = fragments.coordinates
coordinates = coordinates + 10000
coordinates = coordinates / 20000

mapping = fragments.mapping
mapping_cutsites = torch.bincount(mapping[:, 1]) * 2
# calculate the range that contains 90% of the data
sorted_tensor, _ = torch.sort(mapping_cutsites)
ten_percent = mapping_cutsites.numel() // 10
min_val, max_val = sorted_tensor[ten_percent], sorted_tensor[-ten_percent]

#%%
values, bins, _ = plt.hist(mapping_cutsites.numpy(), bins=50, color="blue", alpha=0.75)
percentages = values / np.sum(values) * 100

sns.set_style("white")
sns.set_context("paper", font_scale=1.4)
fig, ax = plt.subplots(dpi=300)
ax.bar(bins[:-1], percentages, width=np.diff(bins), color="blue", alpha=0.75)
ax.set_title("Percentage of values per bin")
ax.set_xlabel("Number of cut sites")
ax.set_ylabel("%")
ax.axvline(min_val, color='r', linestyle='--')
ax.axvline(max_val, color='r', linestyle='--')

sns.despine()

fig.savefig(folder_data_preproc / f'plots/n_cutsites.png')

#%%
csv_dir = folder_data_preproc / "evaluate_pseudo_continuous_tensors"
plot_dir = folder_data_preproc / "plots/evaluate_pseudo_continuous"
plot_combined_dir = folder_data_preproc / "plots/cut_sites_evaluate_pseudo_continuous"

os.makedirs(plot_dir, exist_ok=True)
os.makedirs(plot_combined_dir, exist_ok=True)

def plot_cut_sites(df, gene, n_fragments):
    fig, ax = plt.subplots(figsize=(15, 15))

    ax.scatter(df['x'], df['y'], s=1, marker='s', color='black')
    ax.set_title(f"{gene} (cut sites = {2 * n_fragments})", fontsize=14)
    ax.set_xlabel('Position', fontsize=12)
    ax.set_ylabel('Latent Time', fontsize=12)
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1])
    ax.set_facecolor('white')

    plt.savefig(folder_data_preproc / f'plots/cutsites/{gene}.png')

def plot_cut_sites_histo(df, df_long, gene, n_fragments):
    fig, axs = plt.subplots(figsize=(15, 10), ncols=2, gridspec_kw={'width_ratios': [1, 3]})

    ax_hist = axs[0]
    ax_hist.hist(df['rank'], bins=100, orientation='horizontal')
    ax_hist.set_xlabel('n cells')
    ax_hist.set_ylabel('Rank')
    ax_hist.set_ylim([0, 1])
    ax_hist.invert_xaxis()

    ax_scatter = axs[1]
    ax_scatter.scatter(df_long['x'], df_long['y'], s=1, marker='s', color='black')
    ax_scatter.set_xlabel('Position')
    ax_scatter.set_ylabel('Latent Time')
    ax_scatter.set_xlim([0, 1])
    ax_scatter.set_ylim([0, 1])
    ax_scatter.set_facecolor('white')

    fig.suptitle(f"{gene} (cut sites = {2 * n_fragments})", fontsize=14)

    plt.savefig(folder_data_preproc / f'plots/cutsites_histo/{gene}.png')

def plot_evaluate_pseudo(gene):
    file_name = csv_dir / f"{gene}.csv"
    probsx = np.loadtxt(file_name, delimiter=',')

    fig, ax = plt.subplots(figsize=(10, 10))
    heatmap = ax.imshow(probsx, cmap='RdBu_r', aspect='auto')
    cbar = plt.colorbar(heatmap)

    ax.set_title(f'Probs for gene_oi = {gene}')
    ax.set_xlabel('Position')
    ax.set_ylabel('Latent Time')

    file_name = plot_dir / f"{gene}.png"
    plt.savefig(file_name, dpi=300)

def plot_cut_sites_evaluate_pseudo(df, gene, n_fragments):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 20))

    # Plot cut sites
    ax1.scatter(df['x'], df['y'], s=1, marker='s', color='black')
    ax1.set_title(f"{gene} (cut sites = {2 * n_fragments})", fontsize=14)
    ax1.set_xlabel('Position', fontsize=12)
    ax1.set_ylabel('Latent Time', fontsize=12)
    ax1.set_xlim([0, 1])
    ax1.set_ylim([0, 1])
    ax1.set_facecolor('white')

    # Plot evaluated probabilities
    file_name = csv_dir / f"{gene}.csv"
    probsx = np.loadtxt(file_name, delimiter=',')
    heatmap = ax2.imshow(probsx, cmap='RdBu_r', aspect='auto')
    cbar = plt.colorbar(heatmap)

    ax2.set_title(f'Probs for gene_oi = {gene}')
    ax2.set_xlabel('Position')
    ax2.set_ylabel('Latent Time')

    file_name = plot_combined_dir / f"{gene}.png"
    plt.savefig(file_name, dpi=300)

import matplotlib.pyplot as plt
import numpy as np

def plot_cut_sites_evaluate_pseudo(df, gene, n_fragments):
    fig = plt.figure(figsize=(15, 20))
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1])

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    # Plot cut sites
    ax1.scatter(df['x'], df['y'], s=1, marker='s', color='black')
    ax1.set_title(f"{gene} (cut sites = {2 * n_fragments})", fontsize=14)
    ax1.set_xlabel('Position', fontsize=12)
    ax1.set_ylabel('Latent Time', fontsize=12)
    ax1.set_xlim([0, 1])
    ax1.set_ylim([0, 1])
    ax1.set_facecolor('white')

    # Plot evaluated probabilities
    file_name = csv_dir / f"{gene}.csv"
    probsx = np.loadtxt(file_name, delimiter=',')
    heatmap = ax2.imshow(probsx, cmap='RdBu_r', aspect='auto')

    ax2.set_title(f'Probs for gene_oi = {gene}')
    ax2.set_xlabel('Position')
    ax2.set_ylabel('Latent Time')

    # Create divider for colorbar
    divider = fig.add_axes([0.1, 0.08, 0.8, 0.02])  # [left, bottom, width, height]
    cbar = plt.colorbar(heatmap, cax=divider, orientation='horizontal')

    plt.tight_layout()  # Adjust spacing between subplots

    # Save the combined figure
    file_name = plot_combined_dir / f"{gene}.png"
    plt.savefig(file_name, dpi=300)

plt.ioff()
for x in range(promoters.shape[0]):

    gene = promoters.index[x]
    gene_ix = fragments.var.loc[gene]['ix']
    mask = mapping[:,1] == gene_ix
    mapping_sub = mapping[mask]
    coordinates_sub = coordinates[mask]
    n_fragments = coordinates_sub.shape[0]

    tens = torch.cat((mapping_sub, coordinates_sub), dim=1)
    df = pd.DataFrame(tens.numpy())
    df.columns = ['cell_ix', 'gene_ix', 'cut_start', 'cut_end']
    df['height'] = 1

    df = pd.merge(df, latent_time, left_on='cell_ix', right_index=True)
    df_long = pd.melt(df, id_vars=['cell_ix', 'gene_ix', 'cell', 'latent_time', 'rank', 'height'], value_vars=['cut_start', 'cut_end'], var_name='cut_type', value_name='position')
    df_long = df_long.rename(columns={'position': 'x', 'rank': 'y'})
    
    # plot_cut_sites(df_long, gene, n_fragments)
    # plot_cut_sites_histo(df, df_long, gene, n_fragments)
    # plot_evaluate_pseudo(gene)
    plot_cut_sites_evaluate_pseudo(df_long, gene, n_fragments)


print(f"Done! Plots saved to {folder_data_preproc}")

# TODO
# select hspc marker genes

#%%
fig, axes = plt.subplots(nrows=4, ncols=4, figsize=(60, 60))

for i, ax in enumerate(axes.flat):
    if i >= promoters.shape[0]:
        # if there are fewer genes than axes, hide the extra axes
        ax.axis('off')
        continue
    
    gene = promoters.index[i]
    gene_ix = fragments.var.loc[gene]['ix']
    mask = mapping[:,1] == gene_ix
    mapping_sub = mapping[mask]
    coordinates_sub = coordinates[mask]
    n_fragments = coordinates_sub.shape[0]

    tens = torch.cat((mapping_sub, coordinates_sub), dim=1)
    df = pd.DataFrame(tens.numpy())
    df.columns = ['cell_ix', 'gene_ix', 'cut_start', 'cut_end']
    df['height'] = 1

    df = pd.merge(df, latent_time, left_on='cell_ix', right_index=True)
    df_long = pd.melt(df, id_vars=['cell_ix', 'gene_ix', 'cell', 'latent_time', 'rank', 'height'], value_vars=['cut_start', 'cut_end'], var_name='cut_type', value_name='position')
    df_long = df_long.rename(columns={'position': 'x', 'rank': 'y'})

    ax.scatter(df_long['x'], df_long['y'], s=1, marker='s', color='black')
    ax.set_title(f"{gene} (cut sites = {2 * n_fragments})", fontsize=12)
    ax.set_xlabel('Position', fontsize=10)
    ax.set_ylabel('Latent Time', fontsize=10)
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1])
    ax.set_facecolor('white')

# adjust spacing between subplots
plt.subplots_adjust(hspace=0.5, wspace=0.5)
plt.savefig(folder_data_preproc / f'plots/cutsites_subplot.png')
 
#%%
plot_dir = folder_data_preproc / "plots/evaluate_pseudo_continuous_3D"

for gene_oi in range(promoters.shape[0]):
    file_name = csv_dir / f"tensor_gene_oi_{gene_oi}.csv"
    probsx = np.loadtxt(file_name, delimiter=',')

    fig = go.Figure(data=[go.Surface(z=probsx)])
    fig.update_layout(title=f'Probs for gene_oi = {gene_oi}', template='plotly_white')
    fig.show()
    if gene_oi == 3:
        break