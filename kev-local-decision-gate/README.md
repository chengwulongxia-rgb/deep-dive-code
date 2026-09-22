# Kev local decision gate

> 把 Kev 的語意判斷接進 agent，不把付款權交給它。

這是一個可執行的深度實作：它對一筆客服案件同時問 Kev 兩件事：

1. `Choice`：該交給 billing、shipping 還是 returns？
2. `Noul`：是否可直接核准退款？

模型只負責從非結構化文字判斷；真正不可逆的授權，仍由可讀、可測、可審計的 Python 規則決定：退款不得超過 **$200**、部門信心須至少 **0.85**、退款信心須至少 **0.90**。任一條不滿足就升級人工。

## Clone 後直接跑

```bash
git clone https://github.com/chengwulongxia-rgb/deep-dive-code.git
cd deep-dive-code/kev-local-decision-gate
uv sync
uv run python main.py
```

輸出使用的是明確標示的**離線 fixture**，不假裝它是模型：

```text
department=billing (91%)
refund_probability=73%
action=escalate_to_human
source=offline fixture (pass --kev-url to call a self-hosted Kev server)
```

產生離線決策邊界圖：

```bash
uv run python main.py --chart artifacts/decision-boundary.png
```

測試完整的 HTTP client contract 與兩條安全邊界：

```bash
uv run python -m unittest discover -s tests -v
```

## Google ADK：真正省在 LLM 前面

把 Kev 放進 `before_tool_callback` 能擋危險 tool call，卻不能省掉該輪 Gemini 已經看過所有 tool schema、已經做過 planning 的成本。本實作改在 **ADK Runner 之前** dispatch：

```text
user ticket → Kev Choice → 高信心：窄工具 ADK agent → Gemini
                           低信心：全工具 supervisor → Gemini
```

`adk_dispatch.py` 將案件導到 `billing_agent`、`shipping_agent` 或 `returns_agent`；每個 agent 只帶自己需要的 function tools。Kev 信心低於 0.85、選 `supervisor`、或 response 失效時，才回到保有全部工具的 `supervisor_agent`。

這不是用較小模型取代 Gemini，而是讓 Gemini 少做一個它不擅長、又高頻的「從八個工具中先猜哪三個相關」任務。

### 跑真實的 Kev + ADK turn

先啟動自己管理的 Kev server，並設定 Google Gemini 的 key：

```bash
export GOOGLE_API_KEY='你的 Google AI Studio key'
uv run python adk_routed_app.py \
  --kev-url http://localhost:8009 \
  --ticket 'I was charged twice for my order.' \
  --amount 40
```

這會先印出 Kev 選中的 ADK agent 及該 agent 真正暴露的工具清單，才執行該 agent 的 Gemini turn。ADK 由 `google-adk` 2.9.2 建構；本 repo 的單元測試驗證 agent factory、route fallback 與 API contract，沒有拿假延遲冒充真實 speedup。

## 接真正的 Kev

先依照 [jaredpalmer/kev](https://github.com/jaredpalmer/kev) 的文件，在你的電腦或主機上啟動一個相容 `/v1/systemone` 的 Kev server。假設服務在 `http://localhost:8009`：

```bash
uv run python main.py \
  --kev-url http://localhost:8009 \
  --ticket 'I was charged twice for an order that arrived late.' \
  --amount 120
```

這會送出真正的 request：

```json
{
  "model": "kev-latest",
  "state": {"ticket": "...", "refund_amount_usd": 120},
  "questions": {
    "department": {"type": "choice", "criteria": {"billing": "...", "shipping": "...", "returns": "..."}},
    "refund_authorization": {"type": "noul", "criteria": {"true": "...", "false": "..."}}
  }
}
```

程式不需要 TypeSafe API key；它只呼叫你指定的本機 URL。請不要把沒有驗證或身份驗證的 Kev server 公開到網際網路。

## 為什麼不是 `if probability > 0.9: refund()`

模型能理解「重複扣款」和「寄送延遲」的語意，卻不該自行改寫退款額度、安全政策或例外流程。`kev_gate.py` 故意把它們拆開：

- `support_questions()`：模型可回答的受限問題。
- `KevClient`：薄的 HTTP transport，檢查 API response shape。
- `decide_support_case()`：唯一能產生 `auto_authorize` 的地方。

這個界線讓你可以替換模型、重校準機率或調整 prompt，但不會意外改掉高風險行為。

## 限制

- 離線模式只驗證整合和規則，不代表任何模型準確率。
- 閾值 $200／0.85／0.90 是示範值，不是通用安全常數；上線前必須用自己的標註結果量測 accuracy、ECE、錯誤成本與 abstention。
- 真正的支付、刪除資料、封鎖帳號，仍應加上身份、審批、immutable audit log 和 human override。
