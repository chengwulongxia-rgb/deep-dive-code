# LLM cost frontier：固定快照的成本混用核對

本專案承接部落格的CPU算術驗證，完整程式、輸入快照與結果以這個目錄為準，不再放在blog的下載資產目錄。

## 問題與範圍

固定兩項基準的分數下限，比較原配置、兩配置混用，以及只移除GDP.pdf門檻的對照。這不是重新評測模型、訓練路由器或測試真實服務的節費效果。

- 原資料：Jeffery Kline，*Could you get the same AI results for less?*，2026-11-02。
- 原頁：https://jeff-kline.github.io/posts/same-ai-results-for-less/index.html
- 快照來源日期：2026-10-26；原頁衍生計算日期：2026-11-02；本地保存日期：2026-11-06。
- `data/cost-data.json`：原頁內嵌的`task-data` JSON，保留原位元組與雜湊。程式只分析其中`analytics`的45配置，不把其餘任務誤算進本例。
- 模型與推理設定名稱沿用原資料；價格是歷史基準估值，不是現行報價。

## 執行（預設教學命令為離線）

需Python 3.11以上。程式只用標準函式庫，不需要GPU、API key或任何模型服務。

```bash
cd llm-cost-frontier
uv sync --frozen --python 3.13
uv run --frozen python audit_cost.py data/cost-data.json
uv run --frozen python -m unittest discover -s tests -v
```

`uv sync`首次可能需要取得Python直譯器；取得執行環境後，以上核對與測試不需網路。若已有合適的Python，也可直接：

```bash
python audit_cost.py data/cost-data.json
python -m unittest discover -s tests -v
```

保留原CLI行為：省略輸入路徑才會連網讀取作者公開頁面，不會呼叫模型API：

```bash
python audit_cost.py
```

線上資料的SHA-256若已改變，程式會停止，不把新快照冒充歷史結果。

## 結果與對照

- 原配置：每千項基準任務129.649245美元。
- 各占一半的混用：75.177184美元；AA-LCR 82.0%、GDP.pdf 25.6%，均達原門檻。
- 只要求AA-LCR達標時：最便宜單配置為Luna（Max），成本19.367298美元，但GDP.pdf只有22.8%，不符原先的25.6%要求。
- 在原有兩條件下，最便宜的合格單配置仍是Terra（Low）。

`results/cost-audit.json`保留先前公布結果的原位元組；`results/replay.json`為本次從專案內固定資料重跑的CLI輸出。兩者欄位組織不同，測試按對應欄位核對原始精度數值，不以檔名或格式相同代替結果一致。

測試涵蓋固定快照、原結果一致、單一門檻失敗對照、資料變動拒絕，以及離線核對不觸發HTTP請求。原程式同時驗證工作量比例與對偶證書的可行性及成本下界，沒有新增最佳化演算法。

## 檔案

- `audit_cost.py`：原核對程式，搬移時未修改。
- `data/cost-data.json`：原頁固定輸入快照。
- `results/cost-audit.json`：原公開結果。
- `results/replay.json`：本次重新執行輸出。
- `tests/test_audit.py`：離線回歸測試。
- `pyproject.toml`、`uv.lock`：獨立執行環境，不依賴父repo的環境檔。

## 限制與文章

加權分數可核對，不代表真的把工作分出去後就維持相同品質。這裡沒有驗證路由後的題目分布、評測不確定性、延遲、配額、失敗重試或實際帳單；所有運算都在固定候選配置與線性假設下。

圖表與解說留在[對應文章](https://ai.youdonthavefriends.com/llm/ai/deep-analysis/2026/11/06/llm-cost-frontier.html)。來源資料的數字不是本站重新生成的模型輸出。
