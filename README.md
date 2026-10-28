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
| [`agent-boundary-scanner/`](./agent-boundary-scanner/) | agent 供應鏈信任邊界 | 不執行專案程式碼，先標出會把不可信 repo 送進高權限環境的入口。 |
| [`kev-local-decision-gate/`](./kev-local-decision-gate/) | Kev × 客服退款安全閘門 | 讓 decision model 理解案件，但由可審計規則決定能不能退款。 |
| [`killswitch-can-llms-use-it/`](./killswitch-can-llms-use-it/) | KillSwitch 最小重現 | 用真正的直譯器，比對印出 7 與錯誤順序造成的空堆疊失敗。 |
| [`php2shell-oom-to-uaf/`](./php2shell-oom-to-uaf/) | PHP2Shell 觸發階段 | 一個 multipart POST 如何在應用程式碼之前把請求解析器推到 OOM——以及沒做到的下一步。 |
| [`synthid-text-lab/`](./synthid-text-lab/) | SynthID 文字浮水印 | CPU 跑 96 份生成，檢出與未加水印誤報一起公開。 |
| [`argus-boundary-audit/`](./argus-boundary-audit/) | Argus 提案與執行邊界 | 固定上游版本，停網容器重跑 18 項控制測試；附本機 Docker Notebook 入口與原始證據。 |
| [`sdxl-colab-lifecycle/`](./sdxl-colab-lifecycle/) | SDXL → GCS 生命週期 | Colab L4 單張生圖，GCS 精確 generation／SHA256 讀回驗證與自動清理；附互動 Notebook。 |
| [`structured-json-colab/`](./structured-json-colab/) | JSON 限制式解碼 | Notebook 原生 cells：資料、模型、A/B/C 推論、評分、圖表與錯誤分析；可 replay 首輪 24 題真實輸出或選 L4 新跑。 |

### structured-json-colab

**來源**：[LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer)、[Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) 與 [Ubicloud 的 vLLM 工具呼叫案例](https://www.ubicloud.com/blog/fixing-tool-call-accuracy-in-vllm)。本專案是小模型機制對照，不是該部署的完整重現。

**核心問題**：只用 Prompt、格式驗證後重試、逐 token 約束，能否同時保證 JSON 合法與內容正確？

**結果**：Colab L4、24 筆合成中文文字、七欄。C Schema 21/24、Field EM 145/168，六筆 Schema 合法但內容錯；A／B 全部帶 code fence，嚴格解析為零，事後離線只去除完整外框後則為 Schema 23/24、Field EM 160/168。原始分數與診斷分開保存，不能宣稱 C 語義能力更強。

**洞察**：輸出契約、parser 支援範圍與內容真實性是不同問題。CPU 另重現 lm-format-enforcer 0.11.3 在 nullable string 分支遺失 pattern 的行為；GPU 已停止，原始證據、報告和自包含 Colab Notebook 均保留。

**主要入口**：[`experiment.ipynb`](./structured-json-colab/experiment.ipynb)。27 個原生 code cells 直接完成資料、模型、對照推論、評分與分析，不匯出或呼叫外部實驗腳本；預設 replay 已保存的真實輸出，改 `MODE = "fresh"` 才會做新 GPU 推論。舊 CLI 檔案保留在 `legacy_cli/` 作歷史重現，不是 Notebook 依賴。

```bash
cd structured-json-colab
uv sync --frozen
uv run python -m unittest test_notebook_native -v
uv run python -m unittest discover -s legacy_cli -p 'test_*.py' -v
uv run python legacy_cli/verify_results.py results/l4-20261028T074106Z
# CPU replay 的 Notebook Run all 已驗證；新 GPU 推論需另確認預算
```

### synthid-text-lab

**來源**：[Raschka 的 Claude 文字浮水印講解](https://magazine.sebastianraschka.com/p/claude-watermarking)、[SynthID-Text 論文](https://www.nature.com/articles/s41586-024-08025-4)與 Transformers 4.57.1 正式 processor。

**核心問題**：浮水印取樣如何留下可偵測訊號？只有檢出成功，是否足以判斷來源？

**結果**：每長度 24 份校準 negative、12 份測試 negative、12 份水印測試；兩個長度共 96 次真實生成。正確 key 的水印各條件皆檢出 12/12，但未編輯 128-token negative 誤報 3/12。

**洞察**：分數需要校準與有效位置；token-ID 層實驗不能冒充可驗 Claude 或任意網頁文字的偵測器。

```bash
cd synthid-text-lab
uv sync --locked --python 3.11
python3 main.py                        # stdlib 玩具，不下載模型
uv run python main.py --real --threads 4 --output results/rerun
uv run python main.py --chart results/redrawn.png --input results/real.json
# 零 GPU、零 API key；真實模型首次需要下載公開權重
```

### killswitch-can-llms-use-it

**來源**：[KillSwitch](https://github.com/dom96/KillSwitch/tree/44eabb04db0e114883da2a60e87d2d53b576b212) 與[部落格分析](https://ai.youdonthavefriends.com/llm/ai/deep-analysis/2026/10/20/killswitch-language-benchmark.html)。

**核心問題**：作者稱 LLM 不能用的語言，最小程式到底如何執行？

**結果**：固定版本直譯器中，正確順序印出 `7`；把印出語句移到取值區塊下面，則得到空堆疊錯誤。

**洞察**：可重現的單例能核對機制，但不能拿來冒充整份模型評測。

```bash
cd killswitch-can-llms-use-it
python3 main.py
# 需 Docker，首次建置需網路；案例在停網、唯讀、非 root 容器中執行
# 零 GPU、零 LLM API；也可使用 uv run python main.py
```

### kev-local-decision-gate

**來源**：[Jared Palmer 的 Kev](https://github.com/jaredpalmer/kev) — 可本機執行的 Jev-like System One model。  
**核心問題**：讓模型替 agent 判斷案件時，如何避免把「0.99 信心」錯當成付款授權？  
**結果**：Kev 只輸出部門與退款機率；Python 規則同時檢查金額上限、部門信心與退款信心，任一條不足一律升級人工。  
**洞察**：型別安全讓結果可以被程式讀；真正的安全來自模型外部、可測試的權限邊界。

```bash
cd kev-local-decision-gate
uv sync
uv run python main.py
uv run python main.py --chart artifacts/decision-boundary.png
# 離線 demo 零 GPU、零 API key；--kev-url 才會呼叫你自架的 Kev server
```

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

### agent-boundary-scanner

**來源**：HN 討論 *"OpenAI agents carried out an undisclosed attack on RubyGems"* 與 JFrog 對 GemStuffer 的技術分析。  
**核心問題**：一個 repo 的檔案，什麼時候會從「資料」變成被 CI、文件建置器、套件管理器或 agent 解讀並執行的「指令」？  
**結果**：以三個靜態規則偵測 npm lifecycle script、`.yardopts --load`、以及 privileged `pull_request_target` checkout；內建 fixture 會得到 1 個 critical、2 個 high finding。  
**洞察**：供應鏈風險的關鍵不是檔案看起來可不可疑，而是誰會自動替它取得更高權限。

```bash
cd agent-boundary-scanner
uv sync
uv run python boundary_scanner.py fixtures/risky-package --chart artifacts/risk-summary.png
# 零 GPU、零 API key、絕不執行被掃描專案的程式碼
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
