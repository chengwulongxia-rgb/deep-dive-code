# Colab × Kev：中文原句與氣象署 DOM 候選選擇

唯一測試問題：**鹿野鄉今晚的降雨機率**。

不改成英文、不添加「請選預報區／不要選觀測」等提示，也不把預期答案送給模型。這是 Kev-0.8B 在一份真實 DOM 快照上的**表格候選選擇測試**，不是即時天氣服務，不會回報降雨數字，也尚未測試 DOM 改版耐受性。

## 檔案與入口

- `remote_smoke.py`：用官方 Kev 原始碼在 CUDA 上推論，拒絕 CPU fallback 與非 L4 GPU。不開公網 API、不做訓練。
- `run_colab.py`：透過已安裝並完成 ADC 認證的 Colab CLI 建立 L4、探測型號、上傳程式／快照、執行、下載結果，再於 finally 停止**本次**工作階段。
- `cwa_dom.json`：使用一般 `table` DOM 掃描取得的三個可見表格，保留 caption、列欄文字及 rowspan／colspan。不是依網站 class 或特定 ID 寫死 selector；也不是整個 DOM，更不是零前處理。
- `test_remote_smoke.py`：CPU 測試，核對原句逐字相同、候選合法、答案未洩漏、降雨機率欄位保留、輸入界限。
- `results/<UTC>/lifecycle.json`：每輪實際生命週期與清理結果。CLI 的含連線資訊原始紀錄只留在私有 scratch，不當作可公開憑證分享。

## 本機 CLI 執行

需要 Python 3.12+、已安裝 `google-colab-cli` 並完成 `gcloud` ADC 認證。首次取源、安裝依賴與下載權重需要網路；L4 與 Colab 額度是否可用依帳號當時狀態而定。

```bash
cd kev-colab-weather-smoke
python3 -B -m unittest -v test_remote_smoke
python3 -B run_colab.py --approved-l4-20min
```

`--approved-l4-20min` 表示操作者已同意本次 GPU 額度消耗。所有保留的歷次 `lifecycle.json` 耗時會合併計入預算，扣除後於 20 分鐘上限前預留兩分鐘清理；不應刪除失敗輪次來重置預算。腳本不購買額度、不升級 GPU、不停止其他人的 session。

執行完成後必須同時檢查：

1. 下載的 `kev-smoke-result.json` 的 `inference_status`／`status`，不能只看 CLI exit code。
2. 原始 `instructions` 是否仍是使用者原句。
3. `choice`、完整 `probabilities` 與評分端 `expected`。推論成功不等於選對。
4. `lifecycle.json` 中的停止結果與 server session readback。

## 固定版本與環境

- Kev 原始碼：`2074cc44256200bb37540103fa4572901faa10f3`
- 模型：`jaredpalmer/kev-0.8b`，HF revision `bf75a6a8848ea6960ff2ed108d9ed44c2941174f`，由模型 API 的 `v1.0` tag 查得後固定。
- uv：`0.12.2`；使用官方 PyPI manylinux x86_64 wheel，下載後核對 SHA256，再取出 uv binary，不依賴 Colab 的 `python -m venv`。
- 依賴：遵循固定上游的 `uv.lock`，`uv sync --frozen --extra serve --no-dev`。
- 模型載入：CUDA、bf16、torch backend、關閉 fused kernels 與 CUDA graphs；沒有修改 upstream 的模型邏輯。
- 限制：模型卡標示英文；中文是本次直接測試的條件，不因模型較弱而先翻成英文。

## 輸入與評分邊界

來源為使用者指定的中央氣象署頁面：
`https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=1001405`

快照時間在 `cwa_dom.json` 的 `captured_at`。重跑不會自動更新氣象資料；「今晚」未在此階段解析成具體預報時段，因此即使選對表格，也沒有完成真正的天氣回答。

三個候選使用中性的 `table_0`／`table_1`／`table_2` ID，說明欄為 `None`。caption 及欄位文字來自頁面本身，不是額外的人為答案提示。模型輸入是有界的通用表格摘要，不含 CSS class、網站 ID 或正確答案。評分標籤依人工核對的表格語意預先設定，並測試改動評分標籤不會改變模型請求。

## 實際狀態

初次 L4 工作階段的型號檢查通過，但 bootstrap 在 `python -m venv` 時失敗，沒有載入 Kev；該輪已停止，保留失敗生命週期。CLI `exec` 雖回傳 exit 0，stderr 仍有遠端例外，因此不能當成模型成功。第二輪改用核對雜湊的 uv wheel binary，完成真實 CUDA 推論、下載與關閉。

第二輪原句仍是「鹿野鄉今晚的降雨機率」：模型選 `table_0`（即時觀測），預先核對的正確候選是 `table_1`（鄉鎮預報），所以**這個案例選錯**。原始選項機率為 table_0 `0.371`、table_1 `0.369`、table_2 `0.260`，API confidence `0.0565`；這些不是降雨機率，也不是正確率。

實際環境為 NVIDIA L4、Python 3.13.16、PyTorch 2.8.0+cu128、Transformers 5.17.0。原始結果與每個請求保存在 `results/20261027T082658Z/artifacts/kev-smoke-result.json`，摘要在 `results/summary.json`。兩輪生命週期累計約 147 秒，皆已停止；這是本機流程計時，不冒充供應商精確計費秒數。本次 Notebook 已依使用者要求移除；僅保留實驗程式與原始結果，不提供 Notebook 入口。

結論只到「Kev 能在 Colab L4 執行，但此模型／輸入摘要／原句組合選錯候選」。不能從一例推論所有 Kev 模型無法理解中文，也不能把完成推論寫成通過天氣查詢。

## 來源

- 官方程式：<https://github.com/jaredpalmer/kev>
- 模型：<https://huggingface.co/jaredpalmer/kev-0.8b>
- 原始頁面：<https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=1001405>
