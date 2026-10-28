"""Plot saved real-model results; never initializes a model or GPU."""
import json
from pathlib import Path


def plot(report_path, output_path, posthoc=False):
    report=json.loads(Path(report_path).read_text())
    if report.get('status')!='completed' or set(report.get('summary',{}))!={'A','B','C'}:
        raise ValueError('Only a completed three-arm experiment may be plotted')
    summary=report['summary']
    if posthoc:
        diagnostic=json.loads(Path(report_path).with_name('posthoc-fence-diagnostic.json').read_text())
        if diagnostic.get('posthoc') is not True or diagnostic.get('primary_metrics_unchanged') is not True:
            raise ValueError('Not an explicitly labeled offline diagnostic')
        summary=diagnostic['summary']
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    names=['A: Prompt','B: Validate + retry','C: Token constraints']
    colors=['#6baed6','#f5bd62','#70d6a7']
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'figure.facecolor':'#1a1a2e',
        'axes.facecolor':'#1a1a2e','text.color':'#e0e0e0','axes.labelcolor':'#e0e0e0',
        'axes.edgecolor':'#555','xtick.color':'#e0e0e0','ytick.color':'#e0e0e0','grid.color':'#444'})
    fig,axes=plt.subplots(2,2,figsize=(13,8))
    specifications=[('Schema-valid outputs','schema_valid','cases'),('Field exact match','field_correct','field_total'),
                    ('Fully correct records','object_exact','cases'),('Median generation-path latency','latency_median_s',None)]
    for ax,(title,key,denom) in zip(axes.flat,specifications):
        values=[100*summary[a][key]/summary[a][denom] if denom else summary[a][key] for a in ['A','B','C']]
        ax.bar(names,values,color=colors,width=0.6)
        ax.set_title(title,pad=15)
        ax.set_ylabel('Percent' if denom else 'Seconds')
        ax.set_ylim(0,112 if denom else max(values)*1.25)
        ax.grid(axis='y',alpha=0.3)
        ax.set_axisbelow(True)
        for i,a in enumerate(['A','B','C']):
            label=f"{values[i]:.1f}% ({summary[a][key]}/{summary[a][denom]})" if denom else f'{values[i]:.3f} s'
            ax.text(i,values[i]+(2 if denom else max(values)*0.04),label,ha='center',fontsize=10)
    fig.suptitle('Post-hoc diagnostic: one Markdown fence removed' if posthoc else 'Primary result: strict raw JSON, no repairs',fontsize=18,y=0.99)
    n=summary['A']['cases']
    footer=f"Synthetic Chinese text only | {n} cases x {report['fields_per_case']} fields | Qwen2.5-1.5B-Instruct | L4 fp16 greedy, seed 42\nB shares A's first output; retries only format failures. Latency excludes loading, shared index, warmup and validation."
    fig.text(0.5,0.02,footer,ha='center',fontsize=9,color='#aaa')
    fig.tight_layout(rect=(0,0.08,1,0.96))
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(output_path,dpi=150,facecolor='#1a1a2e')
    plt.close(fig)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--posthoc',action='store_true',help='Read labeled offline fence-removal diagnostic, not primary results')
    args=parser.parse_args()
    plot(args.input,args.output,args.posthoc)
