#!/usr/bin/env python3
"""grep vs vector search benchmark — 深度實作 #1

靈感來源：arXiv 2605.15184 "Is Grep All You Need?"
實作：比較 grep（字串精確匹配）與 MiniLM-L6-v2（語意向量檢索）
      在內部知識庫問答任務上的準確率。

用法：uv run python benchmark.py
      uv run python benchmark.py --chart /path/to/output.png
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 無頭模式，不需要 GUI
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


# ─── 配置 ──────────────────────────────────────────────
CORPUS_FILE = Path(__file__).parent / "corpus" / "acmecorp_kb.md"
QUERIES_FILE = Path(__file__).parent / "data" / "queries.json"
TOP_K = 3  # 取前 K 個結果比較


# ─── 文件載入 ────────────────────────────────────────────

def load_documents(path: Path) -> list[dict]:
    """將 corpus 依 doc_N 標題拆成獨立文件。"""
    text = path.read_text(encoding="utf-8")
    # 用 "---" 定義的 doc 區塊分割
    docs = []
    # 策略：用 "## doc_N:" 作為分隔
    parts = re.split(r"\n---\n", text)
    # 過濾掉前言
    doc_parts = []
    for part in parts:
        if part.strip().startswith("## doc_"):
            doc_parts.append(part.strip())
        elif doc_parts:  # 附加到上一個 doc（跨區塊的殘餘內容）
            doc_parts[-1] += "\n" + part

    for part in doc_parts:
        match = re.match(r"## (doc_\d+): (.+)", part)
        if match:
            doc_id = match.group(1)
            title = match.group(2)
            body = part[match.end():].strip()
            docs.append({"id": doc_id, "title": title, "body": body, "full_text": part})

    return docs


def load_queries(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


# ─── grep 搜尋 ──────────────────────────────────────────

def grep_search(query: str, docs: list[dict], top_k: int = TOP_K) -> list[dict]:
    """對所有文件執行 grep，依匹配行數排名。"""
    scored = []
    # 把 query 拆成關鍵字
    keywords = [w for w in re.split(r"[，。？、\s]+", query) if len(w) >= 2]

    for doc in docs:
        text = doc["full_text"]
        # 計算有多少個關鍵字匹配 + 匹配總次數
        match_count = 0
        for kw in keywords:
            # 對中文使用正則（grep 本質）
            match_count += len(re.findall(re.escape(kw), text, re.IGNORECASE))

        scored.append((match_count, doc))

    # 按匹配次數降序
    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]


# ─── 向量搜尋 ────────────────────────────────────────────

class VectorSearcher:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        print(f"  載入 embedding 模型：{model_name} ...", file=sys.stderr)
        self.model = SentenceTransformer(model_name)
        self.doc_embeddings = None
        self.docs = None

    def index(self, docs: list[dict]):
        self.docs = docs
        texts = [d["full_text"] for d in docs]
        print(f"  編碼 {len(texts)} 份文件 ...", file=sys.stderr)
        self.doc_embeddings = self.model.encode(texts, show_progress_bar=False)

    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        query_embedding = self.model.encode([query])
        similarities = cosine_similarity(query_embedding, self.doc_embeddings)[0]
        top_indices = np.argsort(similarities)[::-1][:top_k]
        return [self.docs[i] for i in top_indices]


# ─── 評估 ──────────────────────────────────────────────

def evaluate(
    method: str,
    queries: list[dict],
    docs: list[dict],
    searcher: VectorSearcher | None = None,
) -> dict:
    """對所有查詢執行搜尋並計算準確率。"""
    correct = 0
    total = len(queries)
    results_detail = []
    start = time.time()

    for q in queries:
        if method == "grep":
            results = grep_search(q["query"], docs)
        else:
            results = searcher.search(q["query"])

        # 檢查答案是否出現在任一 top-K 文件中
        found = any(q["answer"] in r["full_text"] for r in results)
        if found:
            correct += 1

        results_detail.append({
            "id": q["id"],
            "query": q["query"],
            "type": q["type"],
            "found": found,
            "top_docs": [r["id"] for r in results],
        })

    elapsed = time.time() - start
    return {
        "method": method,
        "total": total,
        "correct": correct,
        "accuracy": correct / total,
        "elapsed_sec": round(elapsed, 2),
        "details": results_detail,
    }


# ─── 圖表輸出 ──────────────────────────────────────────────

def make_chart(grep_result: dict, vector_result: dict, queries: list[dict],
               output_path: str) -> None:
    """生成 grouped bar chart：grep vs MiniLM 準確率比較。"""

    # 計算各類準確率
    exact_queries = [q for q in queries if q["type"] == "exact"]
    semantic_queries = [q for q in queries if q["type"] == "semantic"]

    grep_exact = sum(1 for d in grep_result["details"] if d["type"] == "exact" and d["found"])
    grep_semantic = sum(1 for d in grep_result["details"] if d["type"] == "semantic" and d["found"])
    vec_exact = sum(1 for d in vector_result["details"] if d["type"] == "exact" and d["found"])
    vec_semantic = sum(1 for d in vector_result["details"] if d["type"] == "semantic" and d["found"])

    categories = ["整體", "精確查詢", "語意查詢"]
    grep_scores = [
        grep_result["accuracy"] * 100,
        grep_exact / len(exact_queries) * 100 if exact_queries else 0,
        grep_semantic / len(semantic_queries) * 100 if semantic_queries else 0,
    ]
    vector_scores = [
        vector_result["accuracy"] * 100,
        vec_exact / len(exact_queries) * 100 if exact_queries else 0,
        vec_semantic / len(semantic_queries) * 100 if semantic_queries else 0,
    ]

    # 畫圖
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 13,
        "axes.titlesize": 16,
        "axes.labelsize": 13,
        "figure.facecolor": "#1a1a2e",
        "axes.facecolor": "#1a1a2e",
        "text.color": "#e0e0e0",
        "axes.labelcolor": "#e0e0e0",
        "axes.edgecolor": "#444",
        "xtick.color": "#e0e0e0",
        "ytick.color": "#e0e0e0",
        "grid.color": "#333",
    })

    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(categories))
    width = 0.32

    bars1 = ax.bar(x - width/2, grep_scores, width, label="grep（字串匹配）",
                   color="#00d4aa", edgecolor="#00d4aa", linewidth=0.8, alpha=0.85)
    bars2 = ax.bar(x + width/2, vector_scores, width, label="MiniLM-L6-v2（向量）",
                   color="#6c8cff", edgecolor="#6c8cff", linewidth=0.8, alpha=0.85)

    # 數字標籤
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{bar.get_height():.0f}%", ha="center", fontsize=12, fontweight="bold",
                color="#00d4aa")
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{bar.get_height():.0f}%", ha="center", fontsize=12, fontweight="bold",
                color="#6c8cff")

    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.set_ylabel("準確率")
    ax.set_title("grep vs 向量搜尋：內部知識庫問答準確率",
                 fontweight="bold", pad=18)
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.legend(framealpha=0.15, edgecolor="#555", fontsize=11,
              loc="upper right")

    # 底部說明
    fig.text(0.5, 0.01,
             "20 份模擬企業文件 × 20 題問答 | 靈感：arXiv 2605.15184 | chengwulongxia-rgb/deep-dive-code",
             ha="center", fontsize=9, color="#888")

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(output_path, dpi=150, facecolor="#1a1a2e", bbox_inches="tight")
    plt.close(fig)
    print(f"  📈 圖表已輸出：{output_path}")


# ─── 主程式 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="grep vs vector search benchmark")
    parser.add_argument("--chart", type=str, default=None,
                        help="輸出準確率長條圖 PNG 路徑")
    args = parser.parse_args()

    print("=" * 60)
    print("grep vs Vector Search Benchmark")
    print("靈感：arXiv 2605.15184 — Is Grep All You Need?")
    print("=" * 60)
    print()

    # 載入資料
    print("[1/3] 載入測試資料 ...")
    docs = load_documents(CORPUS_FILE)
    queries = load_queries(QUERIES_FILE)
    print(f"  文件數：{len(docs)}")
    print(f"  查詢數：{len(queries)}（精確匹配：{sum(1 for q in queries if q['type']=='exact')}，語意：{sum(1 for q in queries if q['type']=='semantic')}）")
    print()

    # 初始化向量搜尋
    print("[2/3] 初始化向量搜尋 ...")
    searcher = VectorSearcher()
    searcher.index(docs)
    print()

    # 執行評估
    print("[3/3] 執行 benchmark ...")
    print()
    grep_result = evaluate("grep", queries, docs)
    vector_result = evaluate("vector", queries, docs, searcher)

    # ─── 結果表格 ───
    print()
    print("=" * 60)
    print("📊 結果")
    print("=" * 60)
    print()
    print(f"{'方法':<20} {'準確率':<12} {'正確/總數':<12} {'耗時':<10}")
    print("-" * 54)
    print(f"{'grep（字串匹配）':<20} {grep_result['accuracy']:.0%}          {grep_result['correct']}/{grep_result['total']}         {grep_result['elapsed_sec']}s")
    print(f"{'MiniLM-L6-v2（向量）':<20} {vector_result['accuracy']:.0%}          {vector_result['correct']}/{vector_result['total']}         {vector_result['elapsed_sec']}s")
    print()

    # 依類型分析
    exact_queries = [q for q in queries if q["type"] == "exact"]
    semantic_queries = [q for q in queries if q["type"] == "semantic"]

    grep_exact = sum(1 for d in grep_result["details"] if d["type"] == "exact" and d["found"])
    grep_semantic = sum(1 for d in grep_result["details"] if d["type"] == "semantic" and d["found"])
    vec_exact = sum(1 for d in vector_result["details"] if d["type"] == "exact" and d["found"])
    vec_semantic = sum(1 for d in vector_result["details"] if d["type"] == "semantic" and d["found"])

    print("📋 依題型分析：")
    print(f"{'題型':<16} {'grep':<10} {'向量':<10}")
    print("-" * 36)
    print(f"{'精確匹配':<16} {grep_exact}/{len(exact_queries)}       {vec_exact}/{len(exact_queries)}")
    print(f"{'語意查詢':<16} {grep_semantic}/{len(semantic_queries)}       {vec_semantic}/{len(semantic_queries)}")
    print()

    # 找出 grep 比向量好的案例
    print("🔍 grep 成功但向量失敗的案例：")
    grep_wins = []
    for g, v in zip(grep_result["details"], vector_result["details"]):
        if g["found"] and not v["found"]:
            grep_wins.append(g)
            print(f"  Q{g['id']} [{g['type']}]: {g['query'][:50]}...")
    if not grep_wins:
        print("  （無）")
    print()

    print("🔍 向量成功但 grep 失敗的案例：")
    vec_wins = []
    for g, v in zip(grep_result["details"], vector_result["details"]):
        if v["found"] and not g["found"]:
            vec_wins.append(v)
            print(f"  Q{v['id']} [{v['type']}]: {v['query'][:50]}...")
    if not vec_wins:
        print("  （無）")
    print()

    # 結論
    print("=" * 60)
    print("💡 觀察")
    print("=" * 60)
    if grep_result["accuracy"] >= vector_result["accuracy"]:
        winner = "grep"
        diff = grep_result["accuracy"] - vector_result["accuracy"]
    else:
        winner = "向量搜尋"
        diff = vector_result["accuracy"] - grep_result["accuracy"]

    print(f"  {winner} 勝出（差距 {diff:.0%}）")
    print(f"  精確查詢：grep 優勢（{grep_exact}/{len(exact_queries)} vs {vec_exact}/{len(exact_queries)}）")
    print(f"  語意查詢：{'向量' if vec_semantic > grep_semantic else 'grep'} 優勢（{vec_semantic}/{len(semantic_queries)} vs {grep_semantic}/{len(semantic_queries)}）")
    print()
    print("  論文觀點：檢索策略的選擇不能只看演算法，harness 設計")
    print("  （如何切分文件、如何呈現結果）同等重要。簡單工具在")
    print("  正確場景下不輸複雜系統。")

    # ─── 圖表輸出 ───
    if args.chart:
        print()
        make_chart(grep_result, vector_result, queries, args.chart)


if __name__ == "__main__":
    main()
