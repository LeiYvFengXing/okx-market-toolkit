"""
OKX 行情数据管道：抓取 K 线 -> 存入 SQLite（幂等去重）。

功能：
  1. 抓取最近 K 线（/market/candles）
  2. 翻页回填多年历史（/market/history-candles）
  3. 存入 SQLite，并自动去重（重复运行不会产生重复数据）

用法：
    python fetch_data.py                      # 抓最近 300 根日线
    python fetch_data.py --backfill 2000      # 翻页回填 2000 根

环境变量（可选）：
    OKX_HOST    # 自定义 API 域名，默认使用备用域名
"""
import argparse
import os
import sqlite3
import time

import pandas as pd

# OKX API 域名。主域名 www.okx.com 在部分地区不可直连，这里默认用备用域名；
# 需要时可临时覆盖：$env:OKX_HOST="https://www.okx.com"
BASE_URL = os.environ.get("OKX_HOST", "https://www.btmkzrhvxpw.com")

DB_PATH = "data/market.db"
KEY_COLS = ["instId", "bar", "ts"]      # 去重键：三个维度缺一不可
CANDLE_COLS = ["ts", "open", "high", "low", "close",
               "vol", "volCcy", "volCcyQuote", "confirm"]


def _to_dataframe(raw, inst_id: str, bar: str) -> pd.DataFrame:
    """原始 K 线 -> DataFrame（时间升序）。"""
    df = pd.DataFrame(raw, columns=CANDLE_COLS)
    # 时间戳是 13 位毫秒值，必须用 int64（Windows 上 int 是 32 位会溢出）
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
    for c in ["open", "high", "low", "close", "vol", "volCcy", "volCcyQuote"]:
        df[c] = df[c].astype(float)
    df["instId"] = inst_id
    df["bar"] = bar
    # 只保留已收盘的 K 线（confirm=1），避免用未走完的数据
    df = df[df["confirm"] == "1"]
    return df.sort_values("ts").reset_index(drop=True)


def fetch_recent(inst_id: str = "BTC-USDT", bar: str = "1D", limit: int = 300) -> pd.DataFrame:
    """抓取最近的 K 线（一次最多 300 根）。"""
    import requests

    resp = requests.get(f"{BASE_URL}/api/v5/market/candles",
                        params={"instId": inst_id, "bar": bar, "limit": str(limit)},
                        timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        raise RuntimeError(f"OKX error: {data.get('code')} {data.get('msg')}")
    return _to_dataframe(data["data"], inst_id, bar)


def fetch_history(inst_id: str = "BTC-USDT", bar: str = "1D",
                  target: int = 2000, pause: float = 0.2) -> pd.DataFrame:
    """翻页回填历史 K 线（用 after 参数不断往前翻）。"""
    import requests

    url = f"{BASE_URL}/api/v5/market/history-candles"
    params = {"instId": inst_id, "bar": bar, "limit": "100"}
    raw, seen = [], set()

    for _ in range(100):                        # 最多翻 100 页，防死循环
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("code") != "0":
            raise RuntimeError(f"OKX error: {data.get('code')} {data.get('msg')}")
        rows = data.get("data", [])
        if not rows:
            break
        new = 0
        for row in rows:                        # rows 是「最新在前」
            if row[0] not in seen:
                seen.add(row[0])
                raw.append(row)
                new += 1
        if len(raw) >= target or new == 0:
            break
        params["after"] = str(int(rows[-1][0]) - 1)   # 以最老一根为界继续往前
        time.sleep(pause)                             # 控速，避免触发限流

    return _to_dataframe(raw, inst_id, bar)


def store(df: pd.DataFrame, db_path: str = DB_PATH, table: str = "klines") -> int:
    """写入 SQLite，幂等去重（重复运行不会产生重复数据）。"""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(db_path) as conn:
        try:
            old = pd.read_sql(f"SELECT * FROM {table}", conn)
            old["ts"] = old["ts"].astype(str)
            df = pd.concat([old, df], ignore_index=True)
        except Exception:
            pass                                # 表还不存在 -> 首次写入

        before = len(df)
        df = df.drop_duplicates(subset=KEY_COLS, keep="last").reset_index(drop=True)
        df.to_sql(table, conn, if_exists="replace", index=False)

    print(f"去重后共 {len(df)} 行（剔除重复 {before - len(df)} 行）-> {db_path}")
    return len(df)


def main():
    ap = argparse.ArgumentParser(description="OKX 行情数据管道")
    ap.add_argument("--inst", default="BTC-USDT", help="交易对（默认 BTC-USDT）")
    ap.add_argument("--bar", default="1D", help="周期（默认 1D）")
    ap.add_argument("--backfill", type=int, default=0,
                    help="翻页回填的根数（不填则只抓最近 300 根）")
    args = ap.parse_args()

    if args.backfill:
        print(f"翻页回填 {args.inst} {args.bar}，目标 {args.backfill} 根 ...")
        df = fetch_history(args.inst, args.bar, target=args.backfill)
    else:
        print(f"抓取最近 {args.inst} {args.bar} K 线 ...")
        df = fetch_recent(args.inst, args.bar)

    print(f"本次获取 {len(df)} 根，区间 {df['ts'].iloc[0]} ~ {df['ts'].iloc[-1]}")
    store(df)


if __name__ == "__main__":
    main()
