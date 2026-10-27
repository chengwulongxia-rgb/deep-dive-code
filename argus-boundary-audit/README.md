# Argus 控制邊界：固定上游測試選集

這個獨立測試包以 **Argus 真正的上游測試**驗證控制流程，沒有另造 Argus、沒有以自寫控制測試替換上游測試。

- 上游：<https://github.com/thomasunise/argus>（MIT）
- 固定 commit：`8cf56b0fe837538b478812652bd46eff60e20f23`
- 選集：`selection.json` 的 **18 個唯一 pytest nodeid**，沿用前輪 manifest 的精確順序。不是完整 suite。
- 情境：SQLite、假 executor、合成事件；不是實際雲端操作、真 LLM 推論，也不是攻擊重播。無付費 API、無外部目標掃描、不需要 GPU。

## 前置條件與執行

需要本機 Python **3.12+**（只用標準函式庫）、Git，以及可使用的本機 Linux Docker daemon；已驗證 Linux amd64。Docker 是信任邊界，不是對惡意 kernel exploit 的完整隔離保證。不要用 sudo 執行 runner。其他 CPU 架構未驗證，固定 wheel 版本也不保證其他平台都提供 wheel。

```bash
cd argus-boundary-audit
python3 -B reproduce.py
```

預設以固定公開 URL fetch 指定 SHA 到 scratch，checkout 時停用 hooks，不執行上游 setup 腳本。也可用現有上游 checkout，runner 會檢查固定 SHA、乾淨狀態與 `.env`：

```bash
python3 -B reproduce.py \
  --source /path/to/clean/argus \
  --output results/my-new-run
```

`--output` 必須不存在或為空，不覆蓋舊證據。來源包含 tracked/untracked 修改時拒絕執行；即使被 Git ignore，實際 `.env`、`.env.local` 等也拒絕。只允許 `.env.example`、`.env.sample`、`.env.template` 範本名稱。請不要把真憑證寫入範本。runner 不清理、不 stash、不修改使用者來源。

Host 暫存使用 `~/.hermes/cache/scratch/`，或明確設定 `ARGUS_SCRATCH` 指定自己的 scratch；拒絕 host `/tmp`、`/var/tmp`。容器內 `/tmp` 則是受限 tmpfs，兩者不同。自建暫存目錄執行後自動清除。

## 網路、依賴與安全邊界

**取源、拉取基底與 build 需要網路；測試 runtime 沒有網路。** 不下載模型，不使用 API key。`requirements.lock` 原封保存前輪 `pip freeze` 的完整 54 個版本 pin（不含 freeze 預設排除的 pip；pip 由固定基底提供）。build 採用公開 PyPI、只接受 wheel、`--no-deps`，並執行 `pip check`。runtime 再核對 freeze 集合與 lock 完全相同。

固定基底：

```text
python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81
```

digest 已交叉核對前輪完整 build log 與本機 image 的 RepoDigests。版本 pins **不是完整 wheel 內容的雜湊保證**，亦不保證未來 PyPI 仍保有 wheel。結果記錄實際 image ID、完整 build log、來源 Git tree/封存 SHA-256 與每個來源檔案 SHA-256；來源 commit SHA 固定，但下載套件內容並未使用 `--require-hashes` 鎖定。不能將版本鎖等同 bit-for-bit image 可重現。

Build context 僅包含本包的 `Dockerfile` 與 `requirements.lock`。Dockerfile 先建立 venv，再切換 UID/GID 65534 才安裝套件，不以隱藏 pip root warning 代替處理。Build 明確使用 `--network host`，僅供公開 PyPI 下載，解決本機 Docker bridge 無法解析 `files.pythonhosted.org` 的實際問題；這不是 runtime 的設定，runtime 仍強制 `--network none`。本入口以 Linux Docker 為驗證平台，不替其他平台自動放寬 runtime 隔離。

Runtime 每次明確設定：

```text
--network none --read-only --cap-drop ALL
--security-opt no-new-privileges --user 65534:65534
--pids-limit 128 --memory 1g --cpus 2
--tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777
HOME=/tmp AI_PROVIDER=none PYTHONDONTWRITEBYTECODE=1
```

來源透過 `git archive` 匯出成獨立目錄，再**唯讀掛載**；tar extraction 先拒絕 traversal、symlink/hardlink、device 與 `.env`，另使用 stdlib `data` filter。沒有掛載 `.git`、host `.env`、憑證、家目錄或 Docker socket。host 子程序使用最小環境，不傳遞 Git override、API keys 或 Docker 登入設定。容器 rootfs 不可寫，只能在自己的 tmpfs 寫入 SQLite/pytest 暫存。

每個命令有 timeout（build 900 秒、fetch 180 秒、runtime 180 秒，其他預設 60 秒）。timeout、Ctrl-C、SIGTERM 均走 finally 清理；SIGKILL、host/daemon 故障不可能保證清理。只移除本次 UUID 命名的容器及 image tag，**從不做全域 prune**；清理後讀回精確名稱確認消失並記錄。Build cache/基底 image 不全域清除。測試失敗、選集偏離、freeze 不一致或清理驗證失敗皆回傳非零。

## 證據與結果

完成版的真實執行證據放在 `results/run-20261027-verified/`：**18/18 個上游測試通過**，Python 3.13.16、pytest 9.1.1，且本次容器與 image tag 的清理已讀回確認。這一輪從公開 URL 安全 fetch 固定 SHA，完整走過預設取源流程。

- `manifest.json`：選集、實際收集/通過 nodeids、來源 SHA/tree/封存及檔案 hashes、環境版本、Docker image ID、容器 ID、清理讀回結果與證據檔 hashes。
- `commands.jsonl`：每個精確 argv、cwd、起始 UTC、耗時、timeout、exit code 與 stdout/stderr 檔名。
- `pytest.stdout.txt`、`pytest.stderr.txt`：完整原始測試輸出，不是手抄的通過摘要。
- `junit.xml`：容器內 pytest 產生的原始 JUnit。因 tmpfs 在容器停止時消失，wrapper 在退出前將其原始 bytes 以 base64 附加到 stdout，host 解碼保存；不是改寫 XML 或從終端摘要合成報告。runner 核對恰為 18 個唯一指定 nodeid，且無 failure/error/skipped。
- `collect.*`、`pip-freeze.*`、`environment.*`、`docker-version.*`、`image-inspect.*`、`runtime-inspect.*`、`docker-build.*`：完整執行及環境證據。
- `cleanup-*`、`verify-*`：本次 UUID 容器/image 的清理及讀回。

`results/runner-tests-red.*` 記錄 runner 尚不存在時的 TDD 失敗（**不是 Argus 失敗**）。`results/verification/` 保存完成後 runner 單元測試、Notebook JSON/code cell 與 Python 語法驗證。這些是 runner 本身的驗證，不能混算進上游 18 項。

保留的前置失敗也有完整原始證據：`results/run-20261027/` 是 bridge DNS 導致 build 失敗；`results/run-20261027-retry1/` 的上游 pytest 已 18 passed，但 runner 原先嘗試在容器退出後 `docker cp` tmpfs 裡的 JUnit，無法取回，因此仍誠實標記 runner 失敗。後續改成退出前 stdout 匯出；`results/run-20261027-final/` 首次完整通過，`results/run-20261027-verified/` 則是包含最終程式與文件 hashes 的再驗證。失敗目錄中的 artifact hashes 是各該歷史版本，不應要求等同最終檔案。

## Runner 測試與 Notebook

```bash
python3 -B -m unittest -v test_reproduce
python3 -B -c 'import ast,json,pathlib; p=pathlib.Path("."); [ast.parse(x.read_text()) for x in p.glob("*.py")]; n=json.loads((p/"reproduce.ipynb").read_text()); [compile("".join(c["source"]),"<notebook>","exec") for c in n["cells"] if c["cell_type"]=="code"]; print("Python + Notebook syntax OK")'
```

`reproduce.ipynb` 是**本機 Docker 的入口**：把 notebook kernel cwd 設為本目錄後執行，會呼叫同一個 `reproduce.py`。無憑證、無預存輸出，沒有另寫 notebook 專用實驗。一般託管 Colab 預設沒有可用 Docker daemon，**不宣稱一般 Colab 可直接跑**；GPU 不會解決這個限制。Notebook JSON 與所有 code cells 已做語法驗證；不是宣稱曾用 Jupyter UI 完整重跑。

## 如何解讀

18 項選集涵蓋 policy/kill switch、agent action 工具、人工核准生命週期、autoresponse guardrails 與 simulator coverage/gap/purge 邊界。通過只能支持這些固定 fixture 與路徑符合上游斷言，不支持「所有風險都被阻擋」、「完整 suite 通過」、「正式雲端已驗證」或「Argus 能防住全部攻擊」。請閱讀 `selection.json` 與固定 SHA 的測試實作再延伸結論。

本包沒有修改上游測試。重跑會重新取源/建 image；首次安裝與 runtime 斷網是兩個階段，不能把整套工作流稱為完全離線。
