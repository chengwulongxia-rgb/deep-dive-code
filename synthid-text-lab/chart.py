"""Read-only plotting: never imports torch/transformers or downloads a model."""
from pathlib import Path


def make_chart(data, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'figure.facecolor':'#151c2b', 'axes.facecolor':'#151c2b',
        'text.color':'#e5e7eb', 'axes.labelcolor':'#e5e7eb', 'axes.edgecolor':'#566177',
        'xtick.color':'#e5e7eb', 'ytick.color':'#e5e7eb', 'grid.color':'#364152', 'font.size':11})
    if data['kind'] == 'toy':
        fig, ax = plt.subplots(figsize=(11, 5))
        labels = [f"{r['condition']}\n{r['origin']}\nkey={r['key']} / n={r['effective_tokens']}" for r in data['rows']]
        ax.bar(range(len(labels)), [r['score'] or 0 for r in data['rows']], color=['#54c7b0' if r['key']==123 else '#f2b761' for r in data['rows']])
        ax.set_xticks(range(len(labels)), labels, fontsize=8)
        ax.set_ylabel('Mean pseudo-random g bit (not probability)')
        ax.set_title('Tournament teaching analogy: fixed text offers no token choice')
        foot = 'Toy only, not full SynthID. Low entropy: only one independent context; a high raw score is not evidence.'
    else:
        fig, axes_grid = plt.subplots(1, len(data['parameters']['lengths']),
                                     figsize=(7.5 * len(data['parameters']['lengths']), 6),
                                     sharey=True, squeeze=False)
        axes = axes_grid[0]
        conditions = ['clean', 'truncate_half', 'delete_10pct', 'replace_10pct']
        for ax, length in zip(axes, data['parameters']['lengths']):
            selected = [r for r in data['summary'] if r['source_length']==length and r['key_condition']=='correct']
            ordered = [next(x for x in selected if x['condition']==c) for c in conditions]
            for origin, color, shift, label in [('watermarked', '#54c7b0', -.18, 'Watermarked detected'),
                                                ('plain', '#db788a', .18, 'Plain false positives')]:
                for j, r in enumerate(ordered):
                    den, num = r[f'{origin}_count'], r[f'{origin}_detected']
                    value = num / den if den else 0
                    ax.bar(j + shift, value, color=color, width=.32,
                           label=label if j == 0 else '_nolegend_')
                    ax.text(j + shift, value + .025, f'{num}/{den}', ha='center', fontsize=10)
            ax.set_xticks(range(4), ['Clean', 'Keep first\n50%', 'Delete\nfloor(10%)', 'Replace\nfloor(10%)'])
            ax.set_ylim(0, 1.26)
            ax.set_title(f'{length} generated tokens; {data["parameters"]["calibration_count"]} calibration negatives')
            ax.legend(loc='upper center', ncols=2, fontsize=9, frameon=False)
            ax.grid(axis='y', alpha=.35)
        axes[0].set_ylabel('Fraction of evaluation samples above threshold')
        fig.suptitle('Public SynthID processor + distilgpt2 / CPU / mean-g detector', fontsize=16)
        foot = 'Threshold = maximum of held-out plain calibration scores + epsilon, separately by source length/edit/key.\nSmall English-only experiment; FP = actual held-out plain detections. Not a Claude detector or 1% FPR guarantee.'
    fig.text(.5, .015, foot, ha='center', fontsize=9, color='#b6c0d0')
    fig.tight_layout(rect=(0, .09, 1, .94))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
