"""Rebuild the self-contained Colab entry point from reviewed sources."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def build():
    def md(text):
        return {'cell_type':'markdown','metadata':{},'source':text.splitlines(keepends=True)}
    def code(text):
        return {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':text.splitlines(keepends=True)}
    names=['benchmark.py','fixtures.json','requirements.txt','bootstrap.py']
    embedded='from pathlib import Path\n'
    for name in names:
        embedded+='Path('+repr('/content/'+name)+').write_text('+repr((HERE/name).read_text())+',encoding="utf-8")\n'
    cells=[
        md('# JSON 格式合法，不代表內容正確：Colab GPU A/B/C 實驗\n\n選擇 **L4 GPU** 後 Run all。24 筆合成中文車輛買賣文字，七個欄位；不是圖片 OCR，也不是重現 Kimi/vLLM 官方部署。\n\nA 只用 Prompt；B 共用 A 的第一次輸出，僅格式／Schema 失敗時重試一次；C 在相同 Prompt 下用 LM Format Enforcer 限制生成。固定 Qwen2.5-1.5B-Instruct revision、seed 42、greedy、fp16。\n\n首次需下載約 3 GB 模型與套件，會花費 Colab 額度。**這份互動 Notebook 不會自動關閉 GPU，下載完成後務必「中斷連線並刪除執行階段」。** 本機 run_colab.py 才有累計 20 分鐘／5 CU 的預算監控與自動停止。不要把 Notebook 當成同樣有帳戶層級預算保護。'),
        code("import subprocess\ns=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],text=True)\nprint(s)\nassert 'L4' in s, '只驗證 L4，不自動換 GPU'\n"),
        md('## 內嵌完整程式與固定輸入\n不依賴本機 Docker、未發布的 repo commit 或待替換網址。Gold 只進評分器，不加入模型請求。'),
        code(embedded),
        md('## 隔離依賴\n驗證固定 uv wheel SHA256，使用獨立 venv 並保留 Colab 的 torch／torchvision，不覆蓋全域套件。'),
        code("import subprocess,sys\np=subprocess.run([sys.executable,'/content/bootstrap.py','--requirements','/content/requirements.txt'],capture_output=True,text=True)\nprint(p.stdout);print(p.stderr,file=sys.stderr)\np.check_returncode()\n"),
        md('## 執行真實模型\n全部固定輸入只跑一次；結果逐筆落盤。失敗也保留 traceback 與部分結果。'),
        code("from datetime import datetime,timezone\nimport json\nOUTPUT='/content/structured-json-output-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')\np=subprocess.run(['/content/structured-json-env/bin/python','/content/benchmark.py','--fixture','/content/fixtures.json','--output',OUTPUT],capture_output=True,text=True)\nprint(p.stdout);print(p.stderr,file=sys.stderr)\np.check_returncode()\n"),
        code("report=json.loads(Path(OUTPUT+'/report.json').read_text())\nprint(json.dumps(report['summary'],ensure_ascii=False,indent=2))\nassert report['status']=='completed'\nassert report['records_written']==72\n"),
        md('## 下載並關閉\n如果執行 cell 失敗，仍可嘗試下載已保存的部分結果。此處的格式合規率、欄位 EM 與整筆正確率分別計算，不互相代替。下載完成後立即中斷連線並刪除執行階段。'),
        code("from google.colab import files\nfiles.download(OUTPUT+'/result.zip')\n"),
    ]
    for i,cell in enumerate(cells):
        cell['id']='cell-'+str(i)
    notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'},'accelerator':'GPU','colab':{'provenance':[]}},'cells':cells}
    (HERE/'experiment.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=2)+'\n')
    print('Notebook built; fixture SHA256',hashlib.sha256((HERE/'fixtures.json').read_bytes()).hexdigest())


if __name__=='__main__':
    build()
