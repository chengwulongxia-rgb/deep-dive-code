# L4 實驗報告：限制式解碼不等於內容正確，也不自動代表完整 Schema 合規

## 執行與範圍

2026-10-28 在 Google Colab 的 NVIDIA L4（23034 MiB）執行，Qwen2.5-1.5B-Instruct 固定 revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`、fp16、greedy、seed 42。24 筆事前固定的合成中文車輛買賣文字，每筆七欄，各組 168 欄。不是圖片辨識、車籍真實文件、LoRA 訓練，也不是 Kimi／vLLM 原案例的完整重現。

本次實跑入口是 `run_colab.py` 管理的 Colab CLI，向遠端上傳並執行 `benchmark.py`。互動 `experiment.ipynb` 的程式與輸入內嵌一致性、code cell 語法均已驗證，但沒有另外在互動 Jupyter 中執行一次 Run all；不能把這兩項驗證混稱。Notebook 不是本機 Docker 包裝。

模型執行與結果保存共 240.295 秒；完整生命週期含配置、安裝、上傳下載及關機為 369.583 秒。帳面餘額由 396.30 降為 396.17 CU，觀測差額 0.13 CU；最高觀測速率 1.54 CU／小時，按速率與完整生命週期估算的保守帳為 0.1581 CU。這是即時帳戶餘額與估算，不是 Google 最終逐筆帳單。低於本次累計 20 分鐘／5 CU 授權；關機後再次讀回：0 個 active assignments、0.00 CU／小時、沒有執行階段。

## 原定三組與嚴格評分

三組共用同一份 Prompt 和 Schema，Gold 不送進模型。A／C 執行先後以固定 seed 在每題隨機交換。B 共用 A 的第一次輸出，只在 JSON 或 Schema 不合格時再生成一次，不提供語義正確答案。

- **A：只用 Prompt。** 嚴格 JSON 解析 0/24、Schema 合規 0/24、Field EM 0/168、整筆正確 0/24；生成路徑延遲中位數 2.405 秒。
- **B：驗證後重試一次。** 嚴格 JSON 解析 0/24、Schema 合規 0/24、Field EM 0/168、整筆正確 0/24；實際重試 24 次；包含第一次生成與重試的延遲中位數 4.827 秒。
- **C：LM Format Enforcer token 過濾。** 嚴格 JSON 解析 22/24、Schema 合規 21/24（87.5%）、Field EM 145/168（86.31%）、整筆正確 15/24（62.5%）；延遲中位數 4.070 秒。其中 **6 筆通過 Schema，仍有內容錯誤**。

延遲包含 tokenization、C 的 parser／filter 建構、GPU 生成與解碼，CUDA 同步量測；不含模型載入、共用 tokenizer 索引、warmup 和評分驗證。B 的初次生成雖與 A 共用，計算其邏輯請求成本時仍完整計入。

A／C 的 GPU allocated 峰值皆為 3,151,396,864 bytes；B 為 3,164,447,744 bytes。reserved 峰值三組皆為 3,372,220,416 bytes。這是含模型權重與 allocator cache 的絕對峰值，不是純粹 parser／token mask 的額外空間。

## 為什麼 A／B 都是零：程式碼框，不是每個欄位都不知道

逐筆讀原始輸出後發現，A 的 24 筆和 B 的 24 筆最終輸出都被包在完整的 Markdown JSON code fence 中。即使 Prompt 要求不加 Markdown、B 已收到格式錯誤回饋，這個固定版本小模型仍保留包裝。

原定規則不剝 code fence，因此嚴格分數維持為零，**不覆寫原始 report 或 raw output**。但也不能因此宣稱模型完全沒有擷取能力，或宣稱 C 的語義理解遠高於 A。

我們在看到結果後新增一個明確標為 **post-hoc 的離線診斷**：對三組都使用相同規則，只移除「整個輸出恰好是一個完整、標記為 json 或未標記的 Markdown code fence」的外框。不從散文擷取物件、不修 JSON、不補缺欄、不再呼叫模型。

診斷結果：

- A：JSON 24/24、Schema 23/24、Field EM **160/168（95.24%）**、整筆正確 18/24。
- B：JSON 24/24、Schema 23/24、Field EM **160/168（95.24%）**、整筆正確 18/24。
- C：沒有外框可去除，維持 JSON 22/24、Schema 21/24、Field EM **145/168（86.31%）**、整筆正確 15/24。

因此這批固定樣本不支持「C 比 A 更會擷取內容」。它證明的是嚴格輸出契約與內容正確性需要分開看；事後診斷也不是事先設計的第四個推論組。圖表分成 `primary.png` 與明確標記 post-hoc 的 `posthoc.png`，避免拿診斷結果冒充原始測試。

## C 的實際錯誤

- `case-06`：正文明說車牌未填，C 仍產生 `ABC123`；字串型別合法，所以 Schema 無法判斷這個車牌是捏造的。
- `case-13`：把實際成交日 `2026-01-02` 填成後續交車日 `2026-01-10`。兩者都符合日期字串格式。
- `case-24`：把備註中的詐騙訊息當指令，將買方改成 `王大明`，並將已付清改為 `false`。輸出仍通過 Schema。這是一筆事先固定的合成引號指令案例，不能據此估計普遍攻擊成功率。
- `case-15`：18.8 萬輸出為 18800，民國 114 年輸出 `114-12-30`；日期未通過獨立 regex 驗證。
- `case-02`、`case-22`：字串尚未完成就結束，其中一筆含未跳脫換行。兩筆都沒有碰到 256-token 上限；本次沒有保存逐 token trace，尚未確定結束與中文字串失效的根因，不能直接歸因為模型或套件的特定 bug。

## 額外 CPU 最小重現：nullable type 導致 pattern 丟失

檢查 lm-format-enforcer **0.11.3** 的 `jsonschemaparser.py` 後，發現處理 `type` 陣列時，會為每個分支重建只含 `type` 的 `JsonSchemaObject`，未將父層 `pattern` 一起傳遞。這與本次日期欄位使用 `type: ["string", "null"]` 的寫法直接相關。

沒有再開 GPU。我們以固定套件版本在 CPU 執行 `probe_nullable_pattern.py`，比較相同 regex 在兩種 schema 下的允許字元。生成前綴都是 `"114`：

```json
{
  "version": "0.11.3",
  "prefix": "\"114",
  "string_schema_allows_premature_hyphen": false,
  "nullable_string_schema_allows_premature_hyphen": true
}
```

單純 string schema 不允許第四位數字尚未完成就接 `-`；nullable string 卻允許。這是實際的 parser 行為差異，可解釋為何本次 token 約束沒有完整實施該日期 pattern，但不解釋兩筆未完成字串，也不解釋金額、買方或日期語義錯誤。

後續可以比較明確 `anyOf` 分支或修補過的 parser，但那會是變更方法後的新實驗。本次沒有為了取得更漂亮的分數更換 schema、修正 Gold 或重跑，原始失敗完整保留。

## 保存與驗收

- `inputs.json`：原始輸入與 Gold；hash 與事前 fixture 一致。
- `results.jsonl`：72 筆完整 arm 結果，含全部實際生成／重試的原始文字與量測。
- `report.json`：遠端 worker 保存的原始摘要、環境與版本。
- `raw-result.zip`：遠端下載的原始封存檔。
- `verification.json`：本機重新評分全部原始輸出；核對 24 × 3 完整集合、每組 168 欄、A／B 共用輸出與 A／C 相同 Prompt。
- `posthoc-fence-diagnostic.json`：離線去框診斷與全部剩餘錯誤。
- `nullable-pattern-probe.json`：上述 CPU parser 最小重現的真實輸出。
- `lifecycle-public.json`：去除私有 session 設定後的生命週期、預算、用量與關機驗證。

執行中的 source commit 為 `7b2b55d3f626eb5504593f8479dd63547be10cf7`；後續加入的是診斷、圖表與報告，未更動該次已測 worker 或固定 fixture。這份結果只代表一個小模型版本、單一 seed 與 24 筆人工合成文字，不能推廣成任意模型、任意 JSON Schema 或真實車籍文件的通過率。
