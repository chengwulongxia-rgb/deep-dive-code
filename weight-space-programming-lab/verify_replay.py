from pathlib import Path
import asyncio,json,sys
import nbformat
from nbclient import NotebookClient
from jupyter_client import AsyncKernelManager
p=Path(__file__).resolve().parent
nb=nbformat.read(p/'weight_edit_colab.ipynb',as_version=4)
nbformat.validate(nb)
km=AsyncKernelManager(kernel_name='python3',transport_encryption='required')
km.kernel_spec.argv[0]=sys.executable
client=NotebookClient(nb,km=km,timeout=180,resources={'metadata':{'path':str(p)}},allow_errors=False)
try:result=client.execute()
finally:
 if km.has_kernel:asyncio.run(km.shutdown_kernel(now=True))
nbformat.write(result,p/'replay-output/verified.ipynb')
errors=[o for c in result.cells for o in c.get('outputs',[]) if o.get('output_type')=='error'];assert not errors
actual=json.loads((p/'replay-output/summary.json').read_text());expected=json.loads((p/'results/l4-20261104/summary.json').read_text());assert actual==expected
print(json.dumps({'cpu_replay':'passed','total':actual['total'],'code_cells_executed':sum(c.cell_type=='code' and c.execution_count is not None for c in result.cells),'cell_errors':len(errors),'interpreter':sys.executable,'metrics':str(p/'replay-output/metrics.png')},indent=2))
