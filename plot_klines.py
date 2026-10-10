"""
K 线可视化：从 SQLite 读取行情，画出 K 线图 + 双均线 + 买卖信号点。

用法：
    python plot_klines.py                                  # 默认 BTC-USDT 日线
    python plot_klines.py --inst ETH-USDT --bar 1D --n 200

输出：
    images/<inst>_<bar>.png
"""
import argparse
import os
import sqlite3

import matplotlib
matplotlib.use("Agg")                       # 无界面环境直接存图
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd

# 中文字体（Windows 自带）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

DB_PATH = "data/market.db"
OUT_DIR = "images"


def load_klines(inst_id: str, bar: str, n: int) -> pd.DataFrame:
    """从 SQLite 读取最近 n 根 K 线。"""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"未找到 {DB_PATH}，请先运行  python fetch_data.py --backfill 2000")

    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql("SELECT * FROM klines", conn)

    df = df[(df["instId"] == inst_id) & (df["bar"] == bar)]
    if df.empty:
        raise ValueError(f"数据库里没有 {inst_id} {bar} 的数据")

    df["ts"] = pd.to_datetime(df["ts"])
    df = df.drop_duplicates(subset=["ts"]).sort_values("ts").tail(n).reset_index(drop=True)
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)
    return df


def plot(df: pd.DataFrame, inst_id: str, bar: str, fast: int = 20, slow: int = 50):
    fast_ma = df["close"].rolling(fast).mean()
    slow_ma = df["close"].rolling(slow).mean()
    signal = (fast_ma > slow_ma).astype(float)

    fig, ax = plt.subplots(figsize=(14, 7))

    # K 线：绿涨红跌（加密货币习惯）
    for i in range(len(df)):
        o, h, l, c = (df.at[i, "open"], df.at[i, "high"],
                      df.at[i, "low"], df.at[i, "close"])
        color = "#26a69a" if c >= o else "#ef5350"
        ax.vlines(i, l, h, color=color, linewidth=0.8)             # 影线
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64,        # 实体
                               max(abs(c - o), (h - l) * 0.003), color=color))

    ax.plot(range(len(df)), fast_ma, color="#1565c0", linewidth=1.3, label=f"MA{fast}（快线）")
    ax.plot(range(len(df)), slow_ma, color="#ef6c00", linewidth=1.3, label=f"MA{slow}（慢线）")

    # 信号点：0->1 买入，1->0 卖出
    chg = signal.diff().fillna(0)
    buys = [i for i in range(len(df)) if chg.iloc[i] > 0]
    sells = [i for i in range(len(df)) if chg.iloc[i] < 0]
    if buys:
        ax.scatter(buys, df["low"].iloc[buys] * 0.98, marker="^", s=110,
                   color="#1b5e20", zorder=5, label="买入信号")
    if sells:
        ax.scatter(sells, df["high"].iloc[sells] * 1.02, marker="v", s=110,
                   color="#b71c1c", zorder=5, label="卖出信号")

    ax.set_title(f"{inst_id} {bar} K 线 + 双均线({fast}/{slow}) —— 最近 {len(df)} 根", fontsize=14)
    ax.set_ylabel("价格 (USDT)")
    ax.legend(loc="upper left", fontsize=11)
    ax.grid(alpha=0.25)

    step = max(len(df) // 10, 1)
    ax.set_xticks(range(0, len(df), step))
    ax.set_xticklabels([d.strftime("%Y-%m") for d in df["ts"].iloc[::step]], rotation=45)

    plt.tight_layout()
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{inst_id}_{bar}.png")
    plt.savefig(out, dpi=110)
    plt.close(fig)

    print(f"图已保存 -> {out}")
    print(f"区间 {df['ts'].iloc[0].date()} ~ {df['ts'].iloc[-1].date()}"
          f" | 买入 {len(buys)} 次 | 卖出 {len(sells)} 次")


def main():
    ap = argparse.ArgumentParser(description="K 线可视化")
    ap.add_argument("--inst", default="BTC-USDT")
    ap.add_argument("--bar", default="1D")
    ap.add_argument("--n", type=int, default=300, help="画最近多少根")
    args = ap.parse_args()

    df = load_klines(args.inst, args.bar, args.n)
    plot(df, args.inst, args.bar)


if __name__ == "__main__":
    main()
