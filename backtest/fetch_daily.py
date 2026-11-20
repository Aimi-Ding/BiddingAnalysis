#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取全市场日线数据，用于竞价策略回测。

数据来源：
  股票列表  push2dycalc.eastmoney.com/api/qt/clist/get
  日线      push2his.eastmoney.com/api/qt/stock/kline/get  (klt=101, fqt=1 前复权)

为什么要抓日线而不是竞价快照：
  东财没有公开的历史「竞价快照」接口（f615 只反映实时值）。
  但集合竞价的结果就是「开盘价」，所以
      历史竞价涨幅 ≈ (开盘价 / 前一日收盘价 - 1) × 100%
  这个重建是精确的，已在 README 里写明依据。

输出：backtest/data/daily.json
  { "300812": {"name": "易天股份", "bars": [["2026-11-20", 开, 收, 量, 换手率], ...]}, ... }
  bars 按日期升序。

用法：
  python3 fetch_daily.py                 # 全市场
  python3 fetch_daily.py --limit 50      # 只抓 50 只（快速验证）
  python3 fetch_daily.py --refresh       # 忽略已有缓存，重抓
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUT_FILE = DATA_DIR / "daily.json"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

LIST_URL = (
    "https://push2dycalc.eastmoney.com/api/qt/clist/get"
    "?fs=m:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80"
    "&fltt=2&invt=2&fields=f12,f14&fid=f3&po=1&pn=1&pz=6000&np=1"
)
KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f56,f61"
    "&klt=101&fqt=1&beg=0&end=20500101&lmt=1000000"
)


def fetch_json(url: str, retries: int = 3, timeout: int = 25):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # 网络抖动重试
            last = exc
            time.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
    raise last  # type: ignore[misc]


def to_secid(code: str) -> str:
    """把 6 位代码转成东财 secid：沪市 1.，深市 0.。"""
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def get_universe() -> list[tuple[str, str]]:
    j = fetch_json(LIST_URL)
    diff = (j.get("data") or {}).get("diff") or []
    out = [(str(x.get("f12") or "").strip(), str(x.get("f14") or "").strip()) for x in diff]
    return [(c, n) for c, n in out if len(c) == 6]


def parse_kline(payload: dict) -> tuple[str, list[list]]:
    data = payload.get("data") or {}
    name = str(data.get("name") or "")
    bars: list[list] = []
    for line in data.get("klines") or []:
        p = line.split(",")
        if len(p) < 5:
            continue
        try:
            bars.append([
                p[0],                      # 日期
                float(p[1]),               # 开盘
                float(p[2]),               # 收盘
                float(p[3] or 0),          # 成交量(手)
                float(p[4] or 0),          # 换手率%
            ])
        except (ValueError, TypeError):
            continue
    return name, bars


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 只，0=全部")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重抓")
    ap.add_argument("--workers", type=int, default=8, help="并发数")
    ap.add_argument("--days", type=int, default=250, help="每只股票只保留最近 N 个交易日，默认 250")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if OUT_FILE.exists() and not args.refresh:
        try:
            existing = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            print(f"已有缓存：{len(existing)} 只，将增量更新")
        except Exception:
            existing = {}

    universe = get_universe()
    if args.limit:
        universe = universe[: args.limit]
    total = len(universe)
    print(f"股票池：{total} 只")

    done = 0
    failed: list[str] = []
    t0 = time.time()

    def work(item: tuple[str, str]):
        code, name = item
        j = fetch_json(KLINE_URL.format(secid=to_secid(code)))
        real_name, bars = parse_kline(j)
        if args.days and len(bars) > args.days:
            bars = bars[-args.days:]
        return code, (real_name or name), bars

    # 只抓还没有缓存的
    todo = [(c, n) for c, n in universe if c not in existing]
    print(f"待抓：{len(todo)} 只（跳过已缓存 {total - len(todo)} 只）")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, it): it for it in todo}
        for fut in as_completed(futures):
            code, name = futures[fut]
            try:
                c, n, bars = fut.result()
                existing[c] = {"name": n, "bars": bars}
                done += 1
            except Exception as exc:
                failed.append(code)
                print(f"  [失败] {code} {name}: {type(exc).__name__}", file=sys.stderr)
            if done % 200 == 0 and done:
                el = time.time() - t0
                rate = done / el if el else 0
                left = (len(todo) - done) / rate if rate else 0
                print(f"  进度 {done}/{len(todo)}  用时 {el:.0f}s  预计剩余 {left:.0f}s", flush=True)
                OUT_FILE.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    OUT_FILE.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    valid = sum(1 for v in existing.values() if len(v.get("bars") or []) >= 30)
    print()
    print(f"完成：成功 {done} 只，失败 {len(failed)} 只")
    print(f"库内合计 {len(existing)} 只，其中日线≥30根的有 {valid} 只")
    print(f"写入：{OUT_FILE}  ({OUT_FILE.stat().st_size/1024/1024:.1f} MB)")
    print(f"总耗时：{time.time()-t0:.0f}s")
    if failed:
        print(f"失败代码：{','.join(failed[:20])}{' ...' if len(failed) > 20 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
