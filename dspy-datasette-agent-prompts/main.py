"""
用 DSPy 優化 SQL agent 的系統提示 —— 龍蝦城武深度實作

重現 Simon Willison 的研究方法：
  1. 建立書店資料庫 + QA dataset
  2. 用 DSPy ReAct agent 回答 SQL 問題
  3. 跑 baseline evaluation
  4. 用 GEPA optimizer 自動優化系統提示
  5. 對比 before/after，觀察 overfitting 現象

用法:
  uv run python main.py              # 完整流程（需 OPENAI_API_KEY）
  uv run python main.py --chart      # 只產生圖表（從已存的結果讀取）
  uv run python main.py --model gpt-4.1-mini --skip-optimize  # 只跑 baseline

環境變數:
  OPENAI_API_KEY     - OpenAI API key（必要）
  OPENAI_BASE_URL    - 自訂 API endpoint（可選）
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Load .env if present
_dotenv = Path(__file__).parent / ".env"
if _dotenv.exists():
    with open(_dotenv) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

import dspy
from dspy.predict.react import Tool

# ── Paths ──────────────────────────────────────────────────────────
HERE = Path(__file__).parent
DB_PATH = HERE / "bookstore.db"
QA_PATH = HERE / "qa_dataset.json"
RESULTS_PATH = HERE / "results.json"
CHART_PATH = HERE / "optimization_results.png"

# ── System prompt (baseline) ───────────────────────────────────────
BASELINE_SYSTEM_PROMPT = """\
You are a SQL query assistant. You answer questions by running SQL queries against a SQLite database.

Rules:
1. Use the list_tables tool first to see what tables are available.
2. Use describe_table to see the columns of a table before querying it.
3. Use run_query to execute read-only SELECT queries.
4. Always filter out cancelled orders unless the question explicitly asks about them.
5. Present results clearly and concisely.
"""


# ── Database tools ─────────────────────────────────────────────────
def list_tables() -> str:
    """列出資料庫中所有資料表"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cur.fetchall()]
    conn.close()
    return "\n".join(tables) if tables else "(no tables)"


def describe_table(table_name: str) -> str:
    """顯示資料表的欄位結構（CREATE TABLE 語句）"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else f"Table '{table_name}' not found"


def run_query(sql: str) -> str:
    """執行唯讀 SELECT 查詢，回傳結果"""
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return "Error: Only SELECT queries are allowed"

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        if not rows:
            result = "(no results)"
        else:
            cols = [desc[0] for desc in cur.description]
            lines = [", ".join(cols)]
            for row in rows:
                lines.append(", ".join(str(v) for v in row))
            result = "\n".join(lines[:30])  # max 30 rows
            if len(rows) > 30:
                result += f"\n... ({len(rows) - 30} more rows)"
    except Exception as e:
        result = f"Error: {e}"
    finally:
        conn.close()
    return result


# ── DSPy tools ─────────────────────────────────────────────────────
sql_tools = [
    Tool(
        func=list_tables,
        name="list_tables",
        desc="列出資料庫中的所有資料表名稱",
    ),
    Tool(
        func=describe_table,
        name="describe_table",
        desc="顯示指定資料表的 CREATE TABLE 語句，包含所有欄位名稱與型別",
        args={"table_name": {"type": "string", "description": "資料表名稱"}},
        arg_types={"table_name": "str"},
        arg_desc={"table_name": "資料表名稱"},
    ),
    Tool(
        func=run_query,
        name="run_query",
        desc="執行唯讀 SELECT SQL 查詢，回傳查詢結果",
        args={"sql": {"type": "string", "description": "要執行的 SELECT SQL 語句"}},
        arg_types={"sql": "str"},
        arg_desc={"sql": "要執行的 SELECT SQL 語句"},
    ),
]


# ── DSPy signature ─────────────────────────────────────────────────
class SQLAssistant(dspy.Signature):
    """Answer natural-language questions about a bookstore database by running SQL queries.
    Use the provided tools: list_tables, describe_table, run_query.
    Filter out cancelled orders unless the question asks about them.
    Return a final_answer with the concise answer to the question."""

    question: str = dspy.InputField(desc="The user's question about the database")
    final_answer: str = dspy.OutputField(desc="The final answer to the user's question")


# ── Metric ─────────────────────────────────────────────────────────
def load_qa_dataset() -> list[dict]:
    with open(QA_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_trainset(qa_data: list[dict], split: str = "train") -> list[dspy.Example]:
    """Build DSPy examples from QA dataset. Split 20 train / 10 test."""
    if split == "train":
        items = qa_data[:20]
    else:
        items = qa_data[20:]

    examples = []
    for item in items:
        ex = dspy.Example(
            question=item["question"],
            gold_answer=item["answer"],
            gold_sql=item["sql"],
        ).with_inputs("question")
        examples.append(ex)
    return examples


def answer_contains_gold(example: dspy.Example, pred, trace=None) -> float:
    """Check if predicted answer contains the gold answer value(s)."""
    gold = example.gold_answer
    if gold is None:
        return 1.0  # open-ended questions — skip scoring
    try:
        answer = pred.final_answer.lower()
    except (AttributeError, TypeError):
        return 0.0

    # Multiple values (comma-separated)
    golds = [g.strip().lower() for g in gold.split(",")]
    score = sum(1 for g in golds if g in answer) / len(golds)
    return score


def safe_metric(example, pred, trace=None, pred_name=None, pred_trace=None) -> float:
    """Safe wrapper around the metric that catches exceptions. GEPA-compatible signature."""
    try:
        return answer_contains_gold(example, pred, trace)
    except Exception:
        return 0.0


# ── Evaluation ─────────────────────────────────────────────────────
def evaluate(agent, examples: list[dspy.Example]) -> dict:
    """Evaluate agent on a set of examples. Returns per-question scores and average."""
    scores = []
    details = []
    for ex in examples:
        try:
            pred = agent(question=ex.question)
            score = safe_metric(ex, pred)
            scores.append(score)
            details.append({
                "question": ex.question,
                "gold_answer": ex.gold_answer,
                "pred_answer": getattr(pred, "final_answer", "ERROR"),
                "score": score,
            })
        except Exception as e:
            scores.append(0.0)
            details.append({
                "question": ex.question,
                "gold_answer": ex.gold_answer,
                "pred_answer": f"ERROR: {e}",
                "score": 0.0,
            })

    avg = sum(scores) / len(scores) if scores else 0.0
    return {"average": avg, "scores": scores, "details": details}


# ── Optimization ───────────────────────────────────────────────────
def run_gepa_optimization(
    agent,
    trainset: list[dspy.Example],
    task_model: str,
    reflection_model: str,
) -> dspy.Module:
    """Run GEPA optimization on the agent."""
    print(f"\n🔄 開始 GEPA 優化...")
    print(f"   Task model: {task_model}")
    print(f"   Reflection model: {reflection_model}")

    from dspy.teleprompt import GEPA

    optimizer = GEPA(
        metric=safe_metric,
        auto="light",
        reflection_lm=dspy.LM(model=f"openai/{reflection_model}", temperature=0.7, max_tokens=2048),
    )

    optimized = optimizer.compile(agent, trainset=trainset)
    return optimized


# ── Main ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DSPy SQL agent prompt optimization")
    parser.add_argument("--model", default="gpt-4.1-mini",
                        help="LLM model for the agent (default: gpt-4.1-mini)")
    parser.add_argument("--reflection-model", default="gpt-4.1-mini",
                        help="LLM model for GEPA reflection (default: gpt-4.1-mini)")
    parser.add_argument("--skip-optimize", action="store_true",
                        help="Skip optimization, only run baseline")
    parser.add_argument("--chart", action="store_true",
                        help="Generate chart from saved results")
    parser.add_argument("--output-chart", default=str(CHART_PATH),
                        help="Chart output path")
    args = parser.parse_args()

    # Check API key (skip for chart-only mode)
    if not args.chart:
        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not api_key:
            print("❌ 請設定 OPENAI_API_KEY 環境變數")
            print("   export OPENAI_API_KEY='***'")
            sys.exit(1)

    # Chart-only mode
    if args.chart:
        if not RESULTS_PATH.exists():
            print("❌ 找不到 results.json，請先跑一次完整流程")
            sys.exit(1)
        with open(RESULTS_PATH) as f:
            results = json.load(f)
        make_chart(results, args.output_chart)
        print(f"📊 圖表已輸出: {args.output_chart}")
        return

    # ── Setup ──────────────────────────────────────────────────────
    print("=" * 60)
    print("🧪 DSPy × SQL Agent 系統提示優化實驗")
    print("=" * 60)

    # Ensure dataset exists
    if not DB_PATH.exists() or not QA_PATH.exists():
        print("📦 建立資料庫與 QA dataset...")
        import subprocess
        subprocess.run(["uv", "run", "python", str(HERE / "make_dataset.py")], check=True)

    # Load QA data
    qa_data = load_qa_dataset()
    trainset = build_trainset(qa_data, "train")
    testset = build_trainset(qa_data, "test")
    print(f"\n📋 QA dataset: {len(qa_data)} 題 (train={len(trainset)}, test={len(testset)})")

    # ── Configure LM ───────────────────────────────────────────────
    lm = dspy.LM(
        model=f"openai/{args.model}",
        api_key=api_key,
        api_base=base_url,
        temperature=0.0,
        max_tokens=2048,
    )
    dspy.settings.configure(lm=lm)
    print(f"🤖 Model: {args.model}")

    # ── Baseline ───────────────────────────────────────────────────
    print(f"\n📏 執行 Baseline evaluation...")
    # Use ReAct with tools and the baseline system prompt
    agent = dspy.ReAct(
        signature=SQLAssistant,
        tools=sql_tools,
        max_iters=10,
    )
    # Inject the baseline system prompt
    agent.instructions = BASELINE_SYSTEM_PROMPT

    print("   Training set:")
    baseline_train = evaluate(agent, trainset)
    print(f"   → Average: {baseline_train['average']:.2%}")

    print("   Test set:")
    baseline_test = evaluate(agent, testset)
    print(f"   → Average: {baseline_test['average']:.2%}")

    if args.skip_optimize:
        results = {
            "model": args.model,
            "baseline_train": baseline_train["average"],
            "baseline_test": baseline_test["average"],
            "optimized_train": None,
            "optimized_test": None,
            "baseline_details": baseline_train["details"] + baseline_test["details"],
        }
        with open(RESULTS_PATH, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Baseline 完成（略過優化）。結果已存至 {RESULTS_PATH}")
        make_chart(results, args.output_chart)
        return

    # ── GEPA Optimization ──────────────────────────────────────────
    try:
        optimized_agent = run_gepa_optimization(
            agent, trainset,
            task_model=args.model,
            reflection_model=args.reflection_model,
        )
    except Exception as e:
        print(f"\n⚠️  GEPA 優化失敗: {e}")
        print("   可能原因: API key 無效、model 名稱錯誤、或網路問題")
        print("   嘗試用 --skip-optimize 只跑 baseline")
        sys.exit(1)

    # ── Optimized evaluation ───────────────────────────────────────
    print(f"\n📏 執行 Optimized evaluation...")
    print("   Training set:")
    opt_train = evaluate(optimized_agent, trainset)
    print(f"   → Average: {opt_train['average']:.2%}")

    print("   Test set:")
    opt_test = evaluate(optimized_agent, testset)
    print(f"   → Average: {opt_test['average']:.2%}")

    # ── Summary ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📊 結果對比")
    print(f"{'='*60}")
    print(f"  Baseline  Train: {baseline_train['average']:.2%}")
    print(f"  Baseline  Test:  {baseline_test['average']:.2%}")
    print(f"  Optimized Train: {opt_train['average']:.2%} ({opt_train['average'] - baseline_train['average']:+.2%})")
    print(f"  Optimized Test:  {opt_test['average']:.2%} ({opt_test['average'] - baseline_test['average']:+.2%})")

    if opt_train['average'] > baseline_train['average'] and opt_test['average'] < baseline_test['average']:
        print(f"\n  ⚠️  典型 overfitting: 訓練集進步但測試集退步！")
        print(f"  這正是 Simon Willison 實驗的核心發現——")
        print(f"  GEPA 優化器找到的 prompt 改進在訓練資料上有效，")
        print(f"  但對未見過的問題反而有害。")

    # ── Save results ───────────────────────────────────────────────
    results = {
        "model": args.model,
        "reflection_model": args.reflection_model,
        "baseline_train": baseline_train["average"],
        "baseline_test": baseline_test["average"],
        "optimized_train": opt_train["average"],
        "optimized_test": opt_test["average"],
        "baseline_details": baseline_train["details"] + baseline_test["details"],
        "optimized_details": opt_train["details"] + opt_test["details"],
        "timestamp": datetime.now().isoformat(),
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n💾 結果已存至: {RESULTS_PATH}")

    # ── Chart ──────────────────────────────────────────────────────
    make_chart(results, args.output_chart)
    print(f"📊 圖表已輸出: {args.output_chart}")


# ── Chart generation ───────────────────────────────────────────────
def make_chart(results: dict, output_path: str):
    """Generate before/after comparison chart."""
    # Use CJK font
    import matplotlib.font_manager as fm
    cjk_fonts = [f for f in fm.fontManager.ttflist if any(
        keyword in f.name.lower() for keyword in ['noto sans cjk', 'wenquan', 'wqy', 'uming', 'ukai']
    )]
    if cjk_fonts:
        # Prefer Noto Sans CJK TC for Traditional Chinese
        preferred = [f for f in cjk_fonts if 'tc' in f.name.lower() and 'noto sans cjk' in f.name.lower()]
        if not preferred:
            preferred = [f for f in cjk_fonts if 'wenquan' in f.name.lower()]
        if not preferred:
            preferred = cjk_fonts
        plt.rcParams["font.family"] = preferred[0].name
    else:
        plt.rcParams["font.family"] = "sans-serif"

    plt.rcParams.update({
        "font.size": 13,
        "axes.titlesize": 16,
        "figure.facecolor": "#1a1a2e",
        "axes.facecolor": "#1a1a2e",
        "text.color": "#e0e0e0",
        "axes.labelcolor": "#e0e0e0",
        "axes.edgecolor": "#444",
        "xtick.color": "#e0e0e0",
        "ytick.color": "#e0e0e0",
        "grid.color": "#333",
    })

    categories = ["Train", "Test"]
    baseline = [
        results.get("baseline_train", 0),
        results.get("baseline_test", 0),
    ]
    optimized = [
        results.get("optimized_train") or 0,
        results.get("optimized_test") or 0,
    ]

    # If no optimization data, only show baseline
    has_opt = results.get("optimized_train") is not None

    x = np.arange(len(categories))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 5.5))

    bars1 = ax.bar(x - width/2, [v * 100 for v in baseline], width,
                    label="Baseline (原始提示)", color="#4ecdc4", edgecolor="#2a8a82", linewidth=0.5)

    if has_opt:
        bars2 = ax.bar(x + width/2, [v * 100 for v in optimized], width,
                        label="GEPA Optimized (優化後)", color="#ff6b6b", edgecolor="#c44", linewidth=0.5)

    # Value labels
    for bar in bars1:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., h + 1, f"{h:.1f}%",
                ha="center", va="bottom", fontsize=12, color="#4ecdc4")
    if has_opt:
        for bar in bars2:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., h + 1, f"{h:.1f}%",
                    ha="center", va="bottom", fontsize=12, color="#ff6b6b")

        # Add delta arrows
    if has_opt:
        for i, (b, o) in enumerate(zip(baseline, optimized)):
            delta = (o - b) * 100
            color = "#2ecc71" if delta >= 0 else "#e74c3c"
            arrow = "↑" if delta >= 0 else "↓"
            ax.annotate(f"{arrow}{abs(delta):.1f}%",
                        xy=(x[i] + width/2, o * 100),
                        xytext=(x[i] + width/2, o * 100 + 6),
                        ha="center", fontsize=11, color=color, fontweight="bold")

    ax.set_ylabel("準確率 (%)")
    ax.set_title("DSPy GEPA 優化前後對比 — SQL Agent 系統提示", pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.legend(loc="lower right", facecolor="#2a2a3e", edgecolor="#444")
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="y", alpha=0.3)

    fig.text(0.5, 0.01,
             f"資料來源：書店資料庫 QA dataset (30 題) | 模型：{results.get('model', 'N/A')} | "
             f"優化器：DSPy GEPA (auto=light)",
             ha="center", fontsize=9, color="#888")

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(output_path, dpi=150, facecolor="#1a1a2e", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
