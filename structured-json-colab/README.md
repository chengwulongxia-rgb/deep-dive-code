# JSON 結構化輸出：Notebook 原生實驗

**主要入口：[experiment.ipynb](experiment.ipynb)。實驗程式直接寫在 Notebook cells 裡，不再產生或呼叫外部 Python 實驗檔。**

資料與 Gold、Schema、Prompt、模型載入、A／B／C 生成、評分、圖表、錯誤案例、nullable pattern 探針和結果匯出，都能在同一本 Notebook 逐格閱讀、修改和執行。

## 怎麼用

把 `experiment.ipynb` 上傳 Colab，或從 GitHub 開啟。第一個設定 cell 有：

```python
MODE = "replay"        # 或改為 "fresh"
MAX_CASES = 24
INSPECT_CASE_ID = "case-24"
```

- **replay（預設）**：讀取首輪真實 Colab L4 輸出，驗證固定 commit 的檔案 SHA256，在 Notebook 重新評分全部 72 筆結果、重畫圖、檢查錯誤。沒有新模型推論，圖中的延遲／VRAM 取自首輪測量，不花 GPU 額度。
- **fresh**：先在 Colab 選擇 L4，修改 MODE 後 Run all。模型與 token 過濾都在**目前 Notebook kernel** 直接執行，不是 subprocess 或 Docker 包裝。第一次會下載公開權重並使用 GPU；請先確認新預算，下載結果後手動中斷連線並刪除執行階段。

Notebook 的 fresh 依賴安裝使用獨立目錄，保留 Colab 原有 torch／numpy；不把實驗藏進另一個 Python 環境。Notebook 本身不提供帳戶層級 CU 硬上限，不能把首輪 CLI 的預算保護當作互動 Notebook 的保證。

## Notebook 裡有什麼

1. 可修改的模型、revision、seed、token 上限與模式。
2. 六組可直接編輯的合成中文原文與 Gold。
3. 輸出 Schema 與三組共用 Prompt。
4. 嚴格 JSON 解析、Schema 驗證、欄位 EM、整筆正確率。
5. A：Prompt only；B：驗證失敗後重試一次；C：token 約束。
6. 直接載入模型與單次生成／延遲／VRAM 量測。
7. 執行完整對照或重評已保存的真實輸出。
8. 原定指標與清楚標記 post-hoc 的 Markdown 去框診斷。
9. 兩張比較圖、指定錯誤案例、nullable pattern CPU 探針。
10. 保存 JSON／JSONL／PNG、封存與下載。

Gold 不會進模型請求。B 共用 A 的第一次輸出，只有格式不合格才重試，不以 Gold 修正語義錯誤。新推論另外保留 token IDs／終止 token，避免只有解碼後文字而無法分析提前結束。

## 已驗證到哪裡

- **改寫後 Notebook**：以乾淨 Jupyter kernel 從頭執行 replay，27 個 code cells 全部完成、零 cell error，72 筆原始輸出重新評分與首輪摘要完全一致；圖表、錯誤分析與匯出皆實際執行。Notebook 內保留這次 replay 的真實 cell outputs。
- **沒有額外啟動 GPU**。這次是 Notebook 結構與 CPU replay Run all 驗證，不宣稱已對改寫後的 fresh 路徑重新跑一次 GPU。
- [本次 Notebook 驗證紀錄](results/notebook-native-replay/validation.json)。

## 首輪實測結果（2026-10-28，歷史證據保留）

Qwen2.5-1.5B-Instruct，revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`，L4、fp16、greedy、seed 42。24 筆合成中文買賣文字 × 七欄，**不是圖片 OCR 或 LoRA**，也不是 Ubicloud 的 Kimi／vLLM 原部署重現。

- C：Schema 21/24，Field EM 145/168（86.31%），整筆正確 15/24；六筆 Schema 合法但內容錯。
- A／B：24/24 筆帶 Markdown code fence，嚴格原始解析為零。事後僅移除完整外框，Schema 23/24、Field EM 160/168（95.24%）；原始分數未覆寫，不能因此宣稱 C 語義更強。
- 固定版本 CPU 探針確認 lm-format-enforcer 0.11.3 的 nullable string 分支遺失 pattern。另有兩筆 C 的未完成中文字串，根因未定位，未為了漂亮分數更改 Gold 或重跑。
- 首輪生命週期 369.583 秒，當時帳面餘額減少 0.13 CU，保守估算 0.1581 CU；GPU 已停止。這不是本次 Notebook replay 的新計費。

[首輪完整報告](results/l4-20261028T074106Z/REPORT.md) · [原始輸出](results/l4-20261028T074106Z/results.jsonl) · [原始摘要](results/l4-20261028T074106Z/report.json)

## 目錄

- `experiment.ipynb`：**目前主要來源與互動入口**，直接編輯 cells。
- `results/`：首輪不可變原始證據，以及本次 Notebook replay 驗證紀錄。
- `test_notebook_native.py`：防止 Notebook 再退化成外部腳本包裝的檢查。
- `legacy_cli/`：首輪 CLI 程式與回歸測試，僅供歷史重現；Notebook 不 import、不呼叫、不依賴這些檔案。

已移除舊 `build_notebook.py` 產生器，避免用 Python 檔重新覆蓋手寫 Notebook。

## 本機檢查（不開 GPU）

```bash
uv sync --frozen
uv run python -m unittest test_notebook_native -v
uv run python -m unittest discover -s legacy_cli -p 'test_*.py' -v
uv run python legacy_cli/verify_results.py results/l4-20261028T074106Z
```

## 來源

- [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
- [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer)
- [Ubicloud：Fixing Tool-Call Accuracy in vLLM](https://www.ubicloud.com/blog/fixing-tool-call-accuracy-in-vllm)
