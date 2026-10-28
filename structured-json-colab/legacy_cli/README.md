# 首輪 CLI 實驗的歷史檔案

這裡保留 2026-10-28 首輪 L4 實驗的腳本、固定 fixture 與回歸測試。原始測量記錄於 `../results/l4-20261028T074106Z/`，執行時 source commit 為 `7b2b55d3f626eb5504593f8479dd63547be10cf7`。

**目前主要實驗來源是 `../experiment.ipynb`。Notebook 不需要這個目錄，也不呼叫其中的腳本。**

CPU-only 的舊結果驗證可從上一層執行：

```bash
uv run python legacy_cli/verify_results.py results/l4-20261028T074106Z
uv run python -m unittest discover -s legacy_cli -p 'test_*.py' -v
```

`run_colab.py` 只為保存首輪流程而留存；它仍讀取上一層既有的 `.private-runs/` 帳本，搬檔不會重置已花費的預算。不能因留有 CLI 參數便把歷史授權當作新 GPU 實驗的許可。首輪 Notebook 包裝產生器已移除，不能用這些腳本覆蓋目前的 Notebook。
