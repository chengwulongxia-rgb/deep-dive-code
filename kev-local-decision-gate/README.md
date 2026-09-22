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
