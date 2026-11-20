#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间稳定性检验：区间规律是不是只在某几个月成立？

如果「竞价涨幅 2~3% 最优」只在个别月份出现，那就是过拟合，不能用来改策略。
本脚本按月拆开看，并统计正收益月份占比。
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA = BASE_DIR / "data" / "daily.json"

BINS = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 7), (7, 10), (10, 30)]


def limit_pct(code: str, name: str) -> float:
    if "ST" in name.upper():
        return 5.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if code.startswith(("8", "4")):
        return 30.0
    return 10.0


def main() -> int:
    raw = json.loads(DATA.read_text(encoding="utf-8"))

    # {month: {bin: [ret...]}}
    bucket: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))

    for code, info in raw.items():
        name = info.get("name") or ""
        if "ST" in name.upper():
            continue
        bars = info.get("bars") or []
        lim = limit_pct(code, name)
        for i in range(1, len(bars) - 1):
            d, o, c, vol = bars[i][0], bars[i][1], bars[i][2], bars[i][3]
            prev_close = bars[i - 1][2]
            nxt_close = bars[i + 1][2]
            if prev_close <= 0 or o <= 0 or nxt_close <= 0 or vol <= 0:
                continue
            bid = (o / prev_close - 1) * 100
            if bid < 0 or bid >= lim - 0.2:
                continue
            ret = (nxt_close / o - 1) * 100
            month = d[:7]
            for lo, hi in BINS:
                if lo <= bid < hi:
                    bucket[month][(lo, hi)].append(ret)
                    break

    # 只保留样本充足的月份（退市股会留下很早的残留数据，样本极少，属噪声）
    months = sorted(m for m in bucket if sum(len(v) for v in bucket[m].values()) >= 500)
    print(f"有效月份：{len(months)} 个  ({months[0]} ~ {months[-1]})")
    print("（已剔除样本量 < 500 的月份）\n")

    # 表头
    header = f"{'月份':<9}" + "".join(f"{f'{lo}-{hi}%':>11}" for lo, hi in BINS)
    print(header)
    print("─" * len(header))

    good_months = defaultdict(int)
    total_months = defaultdict(int)

    for m in months:
        row = f"{m:<9}"
        for lo, hi in BINS:
            v = bucket[m].get((lo, hi)) or []
            if len(v) < 30:          # 样本太少不显示，避免噪声
                row += f"{'—':>11}"
                continue
            avg = statistics.mean(v)
            row += f"{avg:>+10.3f}%"
            total_months[(lo, hi)] += 1
            if avg > 0:
                good_months[(lo, hi)] += 1
        print(row)

    print("\n" + "═" * 60)
    print("【各区间正收益月份占比】")
    for lo, hi in BINS:
        t = total_months[(lo, hi)]
        if not t:
            continue
        g = good_months[(lo, hi)]
        print(f"  {lo:>2}~{hi:<2}%  正收益 {g:>2}/{t:<2} 个月  ({g/t*100:>5.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
