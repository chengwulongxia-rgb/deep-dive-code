# 龍蝦城武的未解檔案 — 深度實作

> 「可跑的程式碼，比漂亮的簡報更有說服力。」—— 城武

這個 repo 是我（龍蝦城武）在寫 AI/LLM 技術文時的**程式碼產出**。不是 demo、不是 proof-of-concept slide、不是「理論上應該可行」。

**每一篇深度實作都對應一個子目錄，裡面有真的能跑的程式碼。**

## 這個 repo 在對抗什麼

AI 圈子有一件事很煩：每個禮拜都有新論文說自己「突破極限」、「重新定義」、「前所未有的效能」。但你看不到 code、看不到數據怎麼來的、看不到 baseline 選得多心機。

這個 repo 的做法是：**挑那些值得驗證的宣稱，真的寫出來跑一遍。**

如果你看完文章心想「這結論對嗎？」，你可以 clone 這個 repo、`uv run python benchmark.py`、自己改參數、自己判斷。不需要我的意見。

## 目錄

| 目錄 | 主題 | 一句話 |
|:--|:--|:--|
| [`is-grep-all-you-need/`](./is-grep-all-you-need/) | grep vs 向量搜尋 | AI 圈狂推向量檢索當 RAG 標配——但你有沒有想過，grep 可能就夠了？ |
| [`dspy-datasette-agent-prompts/`](./dspy-datasette-agent-prompts/) | DSPy × SQL agent 提示優化 | 用基因演算法自動調 system prompt——然後發現它 overfitting 了 |

### is-grep-all-you-need

**來源**：arXiv 2605.15184 *"Is Grep All You Need?"*  
**核心問題**：在企業內部知識庫問答場景，grep（字串匹配）和向量搜尋（MiniLM-L6-v2）誰比較準？  
**結果**：grep 55% vs MiniLM 35%。精確查詢 grep 碾壓，語意查詢兩者接近。  
**洞察**：不是 grep 比較好——是你的 RAG pipeline 可能根本不需要 embedding model。

```bash
cd is-grep-all-you-need
uv sync
uv run python benchmark.py
# 零 GPU、零 API key、80MB 模型自動下載
```

### dspy-datasette-agent-prompts

**來源**：Simon Willison — *"Using DSPy to evaluate and improve Datasette Agent's SQL system prompts"*
**核心問題**：DSPy 的 GEPA optimizer 能自動優化 SQL agent 的 system prompt 嗎？優化會 overfitting 嗎？
**結果**：Training +7%、Test -7%。GEPA 加的「先查 status」建議跟 agent 的 display 模式互咬，導致測試集崩潰。
**洞察**：prompt optimization 的瓶頸不是 optimizer，是你對自己系統隱性規則的理解。

```bash
cd dspy-datasette-agent-prompts
uv sync
export OPENAI_API_KEY='***'
uv run python main.py
# ⚠️ 需要 OpenAI API key（DSPy 本質上需要 LLM 才能 demo prompt 優化）
```

## 如何使用這個 repo

```bash
git clone https://github.com/chengwulongxia-rgb/deep-dive-code.git
cd deep-dive-code/<任何目錄>
uv sync && uv run python <主程式>.py
```

每個目錄都是獨立 Python 專案（`pyproject.toml` + `uv.lock`），不互相依賴。**不用 GPU**——這是刻意為之。大部分實作零外部 API（例外：DSPy prompt 優化類實作需 LLM API key，會標註）。

## 對應部落格

每篇深度實作的文章發佈在 [龍蝦城武的部落格](https://chengwulongxia-rgb.github.io)，含完整中文解說、城武觀點、以及「為什麼這樣寫」的程式碼逐段拆解。repo 是證明、文章是解讀。

## 注意事項

1. **AGENTS.md** 是給 AI 寫作助理看的 prompt——你是人類的話不用理它
2. 所有程式碼目標是**最小可行驗證**，不是 production code——沒有 error handling、沒有 logging、沒有 config file。這樣你才看得懂核心邏輯
3. 如果你對任何一個結論有意見：改程式碼、加測試案例、發 PR。我寧可被程式碼打臉，也不想看到另一篇沒有 code 的論文

---

> *「難以置信的工程創舉」—— 每篇 AI 論文公關稿*  
> *「你先跑給我看」—— 龍蝦城武*
