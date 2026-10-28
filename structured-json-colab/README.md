# JSON 格式合法，內容就正確嗎？

在真正的 Colab **L4 GPU** 上比較三個結構化輸出路徑：

- **A — Prompt only**：要求模型輸出符合 JSON Schema 的物件。
- **B — Validate + retry**：共用 A 的第一次輸出，只在 JSON／Schema 不合格時重試一次；不給 Gold，也不因內容錯誤重試。
- **C — Constrained decoding**：相同 Prompt，加上 LM Format Enforcer 的逐 token 過濾，最後仍由獨立 JSON Schema 驗證器檢查。

這是小模型機制實驗，**不是重現 Ubicloud 的 Kimi／vLLM 部署**，也不是車籍文件 OCR 或 LoRA 訓練。

## 固定條件

- 模型：`Qwen/Qwen2.5-1.5B-Instruct`，revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`。
- `transformers==4.55.4`、`lm-format-enforcer==0.11.3`、`jsonschema==4.25.1`；保留 Colab 原有 torch／CUDA，實際版本寫入結果。
- fp16、greedy、seed 42、最多 256 個新 token，A/C 先後順序以固定 seed 在每題隨機交換；兩條路徑均先用非評估文字 warmup。
- 24 筆人工撰寫的**合成中文車輛買賣文字**，每筆七欄；輸入與 Gold 在推論前固定於 `fixtures.json`。涵蓋缺漏、總價與訂金、民國日期、角色、否定與無關數字；不是獨立抽樣的生產評測集。
- Fixture SHA256：`1349646cfbef0faac427970ed5da7d6212497f6ef70cfdd42265cc9bf4df8cc9`。

## Notebook：直接在 Colab 執行

開啟 [`experiment.ipynb`](experiment.ipynb)，選擇 **L4 GPU** 後 Run all。Notebook 內嵌程式、輸入和安裝腳本，不呼叫本機 Docker、不需要填入未發布的 commit。首次需下載模型與套件。

**互動 Notebook 不會自動關閉執行階段，也沒有帳戶層級 CU 硬上限。下載結果後立即「中斷連線並刪除執行階段」。** 本機 CLI 的監控與清理屬於另一個入口，不能混為一談。

## 本機管理 Colab CLI

先自行完成 Colab CLI 的 ADC 認證，確認沒有其他執行階段，再執行：

```bash
python run_colab.py --approved-l4-20min-5cu
```

這個命令會使用已授權的 L4、將所有嘗試累計在 **20 分鐘／5 CU** 內，保留清理時間，記錄帳戶用量與計費速率，以「餘額差」和「觀測到的最高速率 × 累計時間」較保守者控管。這不是 Google 提供的逐工作 CU 交易明細；帳務顯示可能延遲。若無法核對速率、認證失敗、發現其他執行階段或超過工作預算即停止。只操作本次具名執行階段，不加購、不升級 GPU。初次執行需額外明確同意；此範例不是永久花費授權。

原始 Colab 設定與執行紀錄在 git 忽略的 `.private-runs/`，含下載到本機的結果；不得把憑證與 session 設定提交到 Git。成功的 CLI transport exit code 不代表模型完成，必須讀回 `report.json`、原始 JSONL 及關機後的 sessions。

## 指標與證據

- 嚴格 JSON 解析：不剝 Markdown、不偷偷修復；重複鍵、NaN／Infinity 視為不合格。
- Schema 合規率、Field-level Exact Match、整筆完全正確率分開計算。
- 每組固定 24 × 7 = 168 個欄位；原始 JSON 無效或不是物件時欄位正確數為零。合法物件即使 Schema 不合格，仍逐欄核對，避免把格式與內容混成一個分數；整筆完全正確須同時通過 Schema。
- 延遲包含 tokenization、C 的 parser／filter 建構、GPU 生成與解碼；CUDA 同步量測。不含模型下載／載入、共用 tokenizer 索引、warmup 與評分驗證，這些另有紀錄。B 的邏輯請求成本包含共用的 A 初次輸出與實際重試。
- GPU `max_memory_allocated` 與 `max_memory_reserved` 記錄絕對峰值，包含模型權重與 allocator cache，不可解讀成純粹 token mask 的額外空間。
- `results.jsonl` 保留每次原始文字、分數、重試、token 數、延遲、VRAM 與模型請求 hash；`inputs.json` 保留輸入與 Gold；`report.json` 記錄版本、來源 hash、seed、執行順序與摘要。失敗也保留部分資料與 traceback。

## 本機測試

```bash
uv sync --frozen
uv run python -m unittest discover -s . -p 'test_*.py' -v
uv run python build_notebook.py
```

本機測試不載入模型、不配置 GPU。單元測試中的替身只測評分／重試邏輯，絕不當作實驗輸出。

## 執行狀態

尚未開始 GPU 實測。完成後在此補上真實結果與保存路徑，不能以預期數字替代。

## 參考

- [Qwen2.5-1.5B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
- [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer)
- [Ubicloud：Fixing Tool-Call Accuracy in vLLM](https://www.ubicloud.com/blog/fixing-tool-call-accuracy-in-vllm)
