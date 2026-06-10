# is-grep-all-you-need: grep vs Vector Search Benchmark

深度實作 #1 — 靈感來自 arXiv 2605.15184 "Is Grep All You Need?"

## 跑一次

```bash
uv sync
uv run python benchmark.py
```

不需要 GPU、不需要 API key、不需要外部服務。
首次執行會下載 all-MiniLM-L6-v2（~80MB），之後秒跑。

## 做什麼

比較兩種搜尋策略在內部知識庫問答上的準確率：

| 方法 | 原理 | 代表 |
|:--|:--|:--|
| **grep** | 字串精確匹配 | UNIX 哲學：簡單工具做一件事 |
| **MiniLM-L6-v2** | transformer semantic embedding | 開源 embedding 標竿 |

## 測試資料

20 份模擬的企業內部文件（CEO 簡介、財報、基礎設施、HR 政策…）
+ 20 個問答（11 題精確查詢、9 題語意查詢）

## 典型結果

```
方法                   準確率
grep（字串匹配）        55%
MiniLM-L6-v2（向量）    35%
```

精確查詢 grep 明顯勝出（8/11 vs 5/11），語意查詢兩者接近。
grep 成功但向量失敗的案例比反過來多。

## 洞察

這不是說「grep 永遠比向量搜尋好」——而是：
1. **先試簡單的**：精確匹配在很多場景就是夠用
2. **Harness 比演算法重要**：怎麼切文件、怎麼呈現結果，影響可能大於檢索策略
3. **不要用複雜度換安全感**：用最複雜的工具不代表做對事
