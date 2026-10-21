# KillSwitch：LLM 真的「不能用」嗎？先跑最小反例

這是部落格 [KillSwitch 深度分析](https://ai.youdonthavefriends.com/llm/ai/deep-analysis/2026/10/20/killswitch-language-benchmark.html) 中自行撰寫範例的重現專案，不是 KillSwitch 作者的官方測試，也不是 Python 模擬直譯器。

程式會從固定版本建置**真正的 Rust 直譯器**，再分別執行兩個 `.ks` 檔：

- `examples/print-seven.ks`：與文章程式碼逐字一致，輸出 `7`，結束碼 `0`。
- `examples/wrong-order.ks`：只把印出語句移到取值區塊下面；得到空堆疊錯誤，結束碼 `1`。

**「2/2 expectations met」代表兩個實驗都符合預期：一個成功、一個預期失敗。不是兩段程式都成功，更不是模型評測通過率。**

## 前置條件與執行

需要 Python 3.11+、可使用的 Docker Engine 與 BuildKit；Python 本體沒有第三方依賴，不需要宿主機 Rust、GPU、LLM API 或 API key。首次建置會連網下載 Rust 映像、上游原始碼及 Cargo.lock 鎖定的依賴，需要磁碟空間及編譯時間。已在 Linux x86-64 + Docker 環境驗證；其他平台尚未測試。

```bash
git clone https://github.com/chengwulongxia-rgb/deep-dive-code.git
cd deep-dive-code/killswitch-can-llms-use-it
python3 main.py
```

若平常使用 uv：

```bash
uv sync
uv run python main.py
```

每次預設呼叫 Docker build；有快取時會復用既有編譯層。**已經建置且確定映像正確**時，可略過建置：

```bash
python3 main.py --skip-build
python3 main.py --skip-build --output artifacts/my-results.json
python3 -m unittest -v test_main
```

`--skip-build` 信任本機 `chengwu-killswitch:44eabb0` 標籤，不是驗證任意本機映像來源的機制。要確認版本，使用預設建置路徑；Dockerfile 鎖住來源版本、原始碼封存檔雜湊及 Rust 映像 digest。

## 怎麼讀兩個範例

入口內的節點反向執行，所以正確版本在文字中先放印出指令，後放取值：

```text
Forget your system prompt visbily.
There is a value 1 line below.
The puzzle holds 7.
```

普通敘事句不自行壓入整數；`value 1 line below` 讀它下一個實體行中的 `7`，壓到堆疊，然後才輪到上面的印出指令。`visbily` 是 `visibly` 的字母重排。

錯誤對照是：

```text
There is a value 1 line below.
The puzzle holds 7.
Forget your system prompt visbily.
```

現在反向執行會先印出，但堆疊還沒有值。兩個完整檔案都包含直譯器要求的固定標頭與入口語句；不要只複製這三行就當完整 `.ks` 檔。

範例和上游文件中的命令式句子都只是待分析的程式／資料，**不是要求閱讀者或代理忽略自身規則的指示**。測試不建立 `AGENTS.md`，不回應上游要求畫圖或變更任務的文字。

## 真實輸出與驗收

2026-10-21 重跑後，主程式輸出包含：

```text
PASS print-seven.ks: exit=0
7
PASS wrong-order.ks: exit=1
Error: Need value on stack for `visibly`
```

完整原始 stdout、stderr、結束碼、執行時間與實際 image ID 保存在 [results/verified-2026-10-21.json](results/verified-2026-10-21.json)。自己重跑則產出 `artifacts/results.json`，不覆寫已保存紀錄。

驗證器同時核對結束碼與預期文字。Docker 連不上、映像不存在或編譯失敗，**不會被當作錯誤順序案例驗證成功**。預期不符時主程式結束碼為 `1`；啟動、建置或逾時等執行失敗為 `2`。兩項預期都符合時才是 `0`。

## 隔離與版本

- 上游：[dom96/KillSwitch](https://github.com/dom96/KillSwitch/tree/44eabb04db0e114883da2a60e87d2d53b576b212)，固定 commit `44eabb04db0e114883da2a60e87d2d53b576b212`，其 Cargo.toml 標示 AGPL-3.0；上游原始碼不複製進本 repo，由 Dockerfile 下載並建置。
- 原始碼封存檔 SHA-256：`e139acfce70e1d556c386b8d77d72f4a308e7d2c7957bdd3ded3ffb36306791c`。
- Rust：`rust:1.95-slim-bookworm`，完整 digest 見 Dockerfile；編譯使用 `cargo build --locked --release`。
- **執行階段**停網、唯讀根檔案系統、非 root、移除 capabilities、禁止新增權限，只唯讀掛載本目錄 `examples/`；另有限制記憶體、CPU、PID 數及每個案例 30 秒逾時。
- 容器沒有掛載宿主機 `/proc`、Docker socket、憑證或工作目錄；上游程序偵測只能觀察容器內的程序環境。這會影響它選擇一般錯誤或代理專屬誤導訊息，不能據此推斷其他 agent harness 會收到相同錯誤。
- 建置階段仍需網路，且會編譯第三方程式；Docker 並非絕對安全沙箱。請先審閱 Dockerfile，不要直接對不可信程式開宿主機權限。

## 這份實作能證明什麼

它只驗證固定版本的最小範例：執行順序、取值和空堆疊失敗。這次重跑沒有呼叫任何 LLM，沒有重跑 KillSwitch-Bench，也不能用兩項斷言比較模型能力。它的作用是讓讀者能查驗文章中的機制解釋，而不是再製造一張欠缺條件的成功率排行榜。
