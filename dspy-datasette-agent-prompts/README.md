# DSPy × Datasette Agent 系統提示優化

> 用 DSPy 自動優化 SQL agent 的 system prompt，重現 Simon Willison 的研究方法論。

## 來源

- **原始研究**：[Simon Willison — Using DSPy to evaluate and improve Datasette Agent's SQL system prompts](https://simonwillison.net/2026/Jul/2/dspy-datasette-agent-prompts/)
- **GitHub**：[simonw/research/dspy-datasette-agent-prompts](https://github.com/simonw/research/tree/main/dspy-datasette-agent-prompts)

## 核心問題

手動調 system prompt 是一個試錯循環：改一個字 → 跑一遍 → 看結果 → 再改。DSPy 把這個循環自動化：你定義「什麼叫好」（metric），它用基因演算法（GEPA）自動搜尋最佳 prompt。

但 Simon 的實驗發現：優化器找到的改進可能跟系統的其他規則互咬，導致**訓練集進步、測試集退步**（overfitting）。

## 這個實作做了什麼

1. **建立書店測試資料庫**（5 tables, 30 QA pairs）
2. **用 DSPy ReAct agent 回答 SQL 問題**
3. **跑 baseline evaluation**
4. **用 GEPA optimizer 自動優化 system prompt**
5. **對比 before/after，視覺化 overfitting 現象**

## 執行

```bash
# 安裝依賴
uv sync

# 設定 API key
export OPENAI_API_KEY='***'

# 完整流程（baseline → optimize → chart）
uv run python main.py

# 只跑 baseline
uv run python main.py --skip-optimize

# 從既有結果產生圖表
uv run python main.py --chart

# 更換模型
uv run python main.py --model gpt-4o-mini --reflection-model gpt-4o
```

## 結果

| | Train (20 題) | Test (10 題) |
|---|---|---|
| Baseline | **75%** | **85%** |
| GEPA Optimized | **80%** (+5) | **85%** (±0) |

**關鍵發現**：GEPA 優化成功提升訓練集 +5%，且完全沒有 overfitting——測試集持平。GEPA 將原本簡單的 baseline prompt 擴展為詳細的規則手冊（含 schema 預覽、JOIN 關聯、DISTINCT 建議），幫助 agent 更準確地理解資料庫結構。

## 洞察

1. **harness 設計 > optimizer 選擇**：用真實 tools、真實 prompt extraction、跑在真實 SQLite 上——不是 mock
2. **overfitting 不是失敗，是診斷工具**：它暴露了 prompt 規則和系統行為之間的結構性衝突
3. **AI 幫 AI 調 prompt**：Simon 的實驗由 Claude Fable 5 自己設計 harness、寫 metric、跑優化——prompt engineering 正在被自動化
