# SDXL → GCS：Colab GPU 完整生命週期

輸入一段描述，在 Colab L4 生成一張圖，保存圖片／參數／實測數據，逐物件讀回驗證，再關閉本次 GPU。不是常駐服務，不做訓練，不把主機憑證複製到 Colab。

## 已實測的結果

2026-10-28 真實 Colab L4 最終隔離環境執行成功：

- 圖片 1024×1024，固定 seed 42、25 steps；推論 **12.73 秒**。
- GPU peak allocated 為 `11237538816` bytes。實際環境是 Python 3.13.16、PyTorch 2.11.0+cu130、CUDA 13.0。
- GCS 的 image、parameters、metrics、result ZIP、manifest 與 SUCCESS 共 **6 個物件**，各自使用原 generation 重新下載、核對 SHA256；另一次獨立讀回也通過，圖片可解碼且尺寸正確。
- 最終工作階段約 94 秒；包含開發中所有成功／失敗輪次的累計生命週期 **392.94 秒（約 6 分 33 秒）**，低於本次授權 20 分鐘。
- stop 成功；server readback 為無活躍 sessions。這是本機流程計時，不是供應商精確計費秒數。
- 本機 **16 項測試通過**。單元測試中的 fake HTTP session 只驗證程式邏輯；上面的 GCS 證據來自另外的真實雲端執行。

實際圖片、原始 parameters／metrics／manifest、各輪生命週期摘要、來源 SHA256、測試輸出在 [`results/verified-run/`](results/verified-run/)。使用者 bucket 路徑、原始 GCS receipt 與含連線資訊的 CLI logs 保留於本機私有紀錄，不公開。

## 入口一：Notebook

開啟 [`lifecycle.ipynb`](lifecycle.ipynb)，選 L4 GPU。Notebook 自包含相同的生成、隔離安裝及儲存模組，不依賴尚未發布的原始碼網址。

1. 在 Colab 完成互動式 Google 授權並輸入自己的 bucket。
2. 先以 unique probe 檢查 create＋指定 generation GET，再安裝及載入模型。
3. 在隔離環境生成圖片、顯示結果，存入 GCS 並驗證。
4. 下載備份；**確認下載完成後，手動中斷連線並刪除執行階段**。

**驗證邊界：** Notebook 的 schema、Python cell 語法與嵌入檔案一致性已驗證，生成程式、bootstrap 與 GCS 上傳邏輯已在下面的管理路徑真實執行；沒有宣稱已透過 Jupyter UI 整本 Run all。Notebook 的互動式授權／直接上傳路徑尚未端到端驗收。其 subprocess 有剩餘時間限制，但不是涵蓋所有 HTTP 操作的硬性 watchdog，也不會自動 teardown。

## 入口二：受控 CLI（本次實測路徑）

**主機授權與儲存預檢 → 建立 L4 → 隔離安裝 → 生成 → 下載本機備份 → 主機上傳 GCS → 精確 generation 讀回 → finally 停止 → server readback。**

先安裝 Colab CLI 並完成 ADC 認證。主機工具依賴由本目錄 `pyproject.toml`／`uv.lock` 管理；不在主機安裝 CUDA 模型。

```bash
cd sdxl-colab-lifecycle
uv sync --frozen
uv run python -B -m unittest discover -s . -p 'test_*.py' -v
uv run python -B run_colab.py --approved-l4-20min \
  --bucket YOUR_BUCKET --prefix runs/YOUR_UNIQUE_RUN_ID
```

`--approved-l4-20min` 表示操作者已同意這次額度消耗。這個入口在所有 Colab 命令明確使用 `--auth adc`，不購買額度、不升級 GPU、不停止其他 sessions。相同工作樹 `.private-runs/*/lifecycle.json` 的歷次耗時累計扣除，預留兩分鐘清理；不得刪紀錄來重設這次預算。工作截止會跳出 HTTP timeout 重試處理，避免重試吞掉逾時。停止與 readback 各有界等待；主機斷電／被強制終止仍可能阻止 finally，不能保證所有失效模式都能自動清理。

`.private-runs/` 保存各輪生命週期、本機產物與 receipt，已 gitignore。CLI 含連線資訊的完整 logs 保存在主機私有 scratch。失敗生成若仍可取得 ZIP，先下載部分產物再報錯；上傳失敗也不會刪除本機備份。

## 模型與環境

- 模型：`stabilityai/stable-diffusion-xl-base-1.0`
- 固定 revision：`462165984030d82259a11f4367a4eed129e94a7b`
- L4／CUDA 必要，禁止 CPU fallback；SDXL fp16 safetensors，不用 refiner、LoRA 或額外最佳化套件。
- 1024×1024、25 steps、guidance 7.5、seed 42。
- 預設描述：`A small wooden cabin beside a quiet mountain lake at sunrise, watercolor illustration, warm light, no text`。使用者未指定逐字 prompt。
- CUDA Python 套件固定在 `requirements.txt`。`bootstrap.py` 下載固定 uv wheel 並比 SHA256，建立隔離 venv，重用 Colab 的 torch／torchvision。解析時明確 exclude torch，避免解析器額外安裝另一版 torch 而與 Colab torchvision 不相容；安裝後再驗證原 torch 版本與 torchvision import。
- 生成 worker 明確選擇 PyTorch backend，不載入不需要的 TensorFlow／Flax；不是過濾或隱藏錯誤訊息。
- Colab 預載 torch／torchvision／driver 本身沒有鎖死，真實版本記錄於 metrics。固定 seed **不保證跨版本、GPU 或 driver 位元一致**。

開發中第一輪因 CLI transfer argv 錯誤即停；另一輪雖生成成功，但發現全域 pip 依賴衝突；隔離環境第一版又被解析器裝入不同 torch，觸發 torchvision nms 不相容。最終版修正安裝與解析範圍後重跑成功，最終 GPU 安裝與生成 stderr 未出現 warning/error/deprecated/conflict 訊息；所有輪次都已停止並計入累計時間。

主機 ADC 仍會提示未設定 quota project 的 SDK 警告；本次 create/get 實測成功。此警告未被隱藏。如需指定 quota project，應選操作者有權限且 API 設定正確的專案，不由此程式任意開啟 API／計費或修改全域憑證。

## GCS 驗收與失敗行為

- Bucket 必須由操作者提供，程式不建立 bucket，也不變更既有 IAM／ACL。
- 所有物件使用 `ifGenerationMatch=0`，既有內容即使相同也不覆寫。每次使用新的 prefix；部分成功後不要清掉舊檔假裝同一 run 成功。
- 只對 transient 429/500/502/503/504 與 timeout 有界重試；ambiguous commit 先查 metadata，再以該 generation 讀回比 SHA256，不盲目重傳或覆寫。
- 先檢查本機成功狀態與 manifest SHA256／大小，再傳 image、parameters、metrics、ZIP，最後傳 manifest 與 SUCCESS。SUCCESS 自己也讀回驗證。
- receipt 記錄每個 object 的 generation、SHA256 與大小。SUCCESS 本文包含先前物件 receipt，不自我引用；SUCCESS 自身的 receipt 在函式回傳值。
- 機器驗收只證明產物完整、尺寸正確、不是定色圖片與保存成功，不把它當成藝術品質評分。實際圖片也已人工目視確認為木屋、湖泊與山景水彩插畫。

## 來源

- 官方模型：<https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0>
- Diffusers SDXL：<https://huggingface.co/docs/diffusers/api/pipelines/stable_diffusion/stable_diffusion_xl>
- GCS JSON API：<https://cloud.google.com/storage/docs/json_api>
- Colab CLI：<https://github.com/googlecolab/google-colab-cli>
