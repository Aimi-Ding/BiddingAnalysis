#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞价策略回测：验证「9:25 按竞价涨幅排序选股」到底有没有超额收益。

====================== 为什么只测竞价涨幅 ======================
原策略的综合分由 6 个因子加权，但把它们搬到历史数据里，只有「竞价涨幅」能精确重建：

  可精确重建  竞价涨幅 = 开盘价 / 前一日收盘价 - 1   （集合竞价的结果就是开盘价）
  不可得      竞价量、量比、警示类型、历史流通市值（东财不提供历史快照）
  未来函数    「今日涨幅」在 9:25 时尚未产生，用它选股等于偷看未来

所以本回测测的是：**竞价涨幅这一个因子单独的预测能力**。
它的权重在原策略里是 0.32（最大的一项），是竞价时段唯一有真实信息的因子。
这不等于验证了完整综合分，README 里已明确标注。

====================== 收益口径 ======================
  买入  当日开盘价（= 集合竞价成交价）
  卖出  当日收盘价
  收益  (收盘 / 开盘 - 1) × 100%

====================== 必须处理的偏差 ======================
1. 一字涨停买不进：开盘即涨停的股票实际无法买入，必须剔除，否则严重虚高
   涨停幅度按板块判定：创业板/科创板 20%，主板 10%，ST 5%
2. 幸存者偏差：库里只有现存股票，已退市的没算进来
3. ST 判定用当前名称，历史某天的 ST 状态拿不到，可能有出入
4. 未计交易成本（佣金约万2.5、卖出印花税千1、滑点）

用法：
  python3 run_backtest.py                 # 默认参数
  python3 run_backtest.py --top 3,10,30   # 指定看前几名
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA = BASE_DIR / "data" / "daily.json"


def limit_pct(code: str, name: str) -> float:
    """当日涨停幅度（%）。"""
    if "ST" in name.upper():
        return 5.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if code.startswith(("8", "4")):          # 北交所
        return 30.0
    return 10.0


def is_st(name: str) -> bool:
    n = name.upper()
    return "ST" in n or "退" in name


def load_index(data_path: Path | None = None):
    """把日线库重排成「按日期」的截面索引。

    返回 dates: 升序日期列表
         by_date: {date: [ {...}, ... ]}
    """
    path = data_path or DATA
    raw = json.loads(path.read_text(encoding="utf-8"))
    by_date: dict[str, list[dict]] = defaultdict(list)

    for code, info in raw.items():
        name = info.get("name") or ""
        bars = info.get("bars") or []
        # bars: [日期, 开, 收, 量, 换手率]，升序
        for i in range(1, len(bars)):          # 从第 2 根起才有昨收
            d, o, c, vol, turn = bars[i][0], bars[i][1], bars[i][2], bars[i][3], bars[i][4]
            prev_close = bars[i - 1][2]
            if prev_close <= 0 or o <= 0 or c <= 0:
                continue
            nxt_open = bars[i + 1][1] if i + 1 < len(bars) else None
            nxt_close = bars[i + 1][2] if i + 1 < len(bars) else None
            by_date[d].append({
                "code": code,
                "name": name,
                "open": o,
                "close": c,
                "prev": prev_close,
                "vol": vol,
                "turn": turn,
                "bid": (o / prev_close - 1) * 100,      # 竞价涨幅（重建值）
                "ret": (c / o - 1) * 100,               # 口径0：当日收盘卖（T+1下不可执行，仅参考）
                # 口径1（可执行）：D日开盘买，D+1日收盘卖
                "ret1": ((nxt_close / o - 1) * 100) if nxt_close else None,
                # 口径2（可执行）：D日开盘买，D+1日开盘卖
                "ret2": ((nxt_open / o - 1) * 100) if nxt_open else None,
            })
    dates = sorted(by_date)
    return dates, by_date


HOLD_LABELS = {
    0: "D日开盘买 → D日收盘卖（T+1 下不可执行，仅作对照）",
    1: "D日开盘买 → D+1日收盘卖（T+1 可执行）",
    2: "D日开盘买 → D+1日开盘卖（T+1 可执行）",
}


def get_ret(rec: dict, hold: int):
    """按持有口径取收益（%）。"""
    if hold == 0:
        return rec.get("ret")
    if hold == 1:
        return rec.get("ret1")
    if hold == 2:
        return rec.get("ret2")
    return None


def eligible(rec: dict) -> tuple[bool, str]:
    """能否在这天买入。返回 (是否可买, 原因)。"""
    name, code = rec["name"], rec["code"]
    if not name:
        return False, "无名称"
    if is_st(name):
        return False, "ST"
    if rec["vol"] <= 0:
        return False, "停牌"
    if rec["open"] <= 0 or rec["close"] <= 0:
        return False, "无价"

    lim = limit_pct(code, name)
    # 一字涨停：开盘就封在涨停，买不进去
    if rec["bid"] >= lim - 0.2:
        return False, "开盘涨停买不进"
    # 一字跌停：开盘跌停，也难成交（卖不掉但这里是买入，保守起见也剔除）
    if rec["bid"] <= -lim + 0.2:
        return False, "开盘跌停"
    if rec["bid"] < 0:
        return False, "竞价下跌"
    return True, ""


def run(dates, by_date, top_list, bid_cap: float, min_pool: int, hold: int = 1):
    """按竞价涨幅排序选股，统计收益。"""
    daily_rows = []
    picks = {k: [] for k in top_list}
    skipped = defaultdict(int)

    for d in dates:
        pool_all = by_date[d]
        if len(pool_all) < min_pool:
            continue

        # 全市场基准：所有能正常交易（非ST、非停牌、非一字板）的股票等权平均
        ok_all = []
        for r in pool_all:
            good, why = eligible(r)
            if good and get_ret(r, hold) is None:
                good, why = False, "无次日数据"
            if good:
                ok_all.append(r)
            else:
                skipped[why] += 1
        if len(ok_all) < min_pool:
            continue

        bench = sum(get_ret(r, hold) for r in ok_all) / len(ok_all)

        # 模拟「9:25 竞价涨幅榜」：先按竞价涨幅取前 100，再叠加原策略的涨幅上限
        ranked = sorted(ok_all, key=lambda x: -x["bid"])
        if bid_cap is not None:
            ranked = [r for r in ranked if r["bid"] < bid_cap]
        top100 = ranked[:100]
        if not top100:
            continue

        for k in top_list:
            sel = top100[:k]
            if not sel:
                picks[k].append(None)
                continue
            avg = sum(get_ret(r, hold) for r in sel) / len(sel)
            picks[k].append({
                "date": d,
                "n": len(sel),
                "ret": avg,
                "bench": bench,
                "alpha": avg - bench,
                "names": [(r["name"], round(r["bid"], 2), round(r["ret"], 2)) for r in sel],
            })

        daily_rows.append({"date": d, "bench": bench, "pool": len(ok_all)})

    return daily_rows, picks, skipped


def summarize(name: str, rows: list, bench_rows: list):
    rows = [r for r in rows if r]
    if not rows:
        print(f"{name}: 无数据")
        return
    rets = [r["ret"] for r in rows]
    alphas = [r["alpha"] for r in rows]
    bench = [r["bench"] for r in rows]
    wins = sum(1 for x in rets if x > 0)
    beats = sum(1 for x in alphas if x > 0)

    print(f"\n{'─'*62}")
    print(f"【{name}】 交易日 {len(rows)} 天")
    print(f"  日均收益      {statistics.mean(rets):+.3f}%")
    print(f"  收益中位数    {statistics.median(rets):+.3f}%")
    print(f"  胜率(收益>0)  {wins/len(rets)*100:.1f}%  ({wins}/{len(rets)})")
    print(f"  日收益标准差  {statistics.pstdev(rets):.3f}%")
    print(f"  最好 / 最差   {max(rets):+.2f}% / {min(rets):+.2f}%")
    print(f"  ── 对比全市场等权基准（同期 {statistics.mean(bench):+.3f}%/天）")
    print(f"  日均超额      {statistics.mean(alphas):+.3f}%")
    print(f"  跑赢基准天数  {beats/len(alphas)*100:.1f}%  ({beats}/{len(alphas)})")
    cum = 1.0
    for x in rets:
        cum *= (1 + x / 100)
    print(f"  累计净值      {cum:.4f}  （{(cum-1)*100:+.1f}%，单利口径，未复利除成本）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", default="3,10,20,50")
    ap.add_argument("--bid-cap", type=float, default=None,
                    help="竞价涨幅上限（模拟原策略的7%%/9.5%%阈值）。不填=不限")
    ap.add_argument("--min-pool", type=int, default=200, help="当日有效样本少于该值则跳过")
    ap.add_argument("--data", default=None, help="日线库路径，默认 backtest/data/daily.json")
    ap.add_argument("--hold", type=int, default=1, choices=[0, 1, 2],
                    help="持有口径：0=D日收盘卖(不可执行) 1=D+1收盘卖 2=D+1开盘卖，默认1")
    args = ap.parse_args()

    data_path = Path(args.data) if args.data else DATA
    if not data_path.exists():
        print(f"数据不存在，请先运行 fetch_daily.py\n  期望路径：{data_path}")
        return 2

    top_list = [int(x) for x in args.top.split(",") if x.strip()]
    print("载入日线库 ...")
    dates, by_date = load_index(data_path)
    print(f"  交易日 {len(dates)} 天：{dates[0]} ~ {dates[-1]}")
    print(f"  平均每日截面 {sum(len(v) for v in by_date.values())/len(by_date):.0f} 只")

    cap_txt = f"竞价涨幅 < {args.bid_cap}%" if args.bid_cap else "竞价涨幅不限"
    print(f"\n规则：{cap_txt}；{HOLD_LABELS[args.hold]}；已剔除 ST/停牌/一字涨跌停/无次日数据")

    daily_rows, picks, skipped = run(dates, by_date, top_list, args.bid_cap, args.min_pool, args.hold)

    print(f"\n有效交易日 {len(daily_rows)} 天")
    print("剔除统计：", dict(sorted(skipped.items(), key=lambda x: -x[1])))

    for k in top_list:
        summarize(f"竞价涨幅榜 前 {k} 名", picks[k], daily_rows)

    # 竞价涨幅区间 vs 当日收益
    print(f"\n{'═'*62}")
    print(f"【竞价涨幅区间 → 收益】 {HOLD_LABELS[args.hold]}")
    bins = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 7), (7, 10)]
    bucket = defaultdict(list)
    for d in dates:
        for r in by_date[d]:
            good, _ = eligible(r)
            if not good:
                continue
            b = r["bid"]
            rr = get_ret(r, args.hold)
            if rr is None:
                continue
            for lo, hi in bins:
                if lo <= b < hi:
                    bucket[(lo, hi)].append(rr)
                    break
    print(f"  {'区间':>10} {'样本数':>9} {'日均收益':>10} {'胜率':>8}")
    for lo, hi in bins:
        v = bucket.get((lo, hi)) or []
        if not v:
            continue
        w = sum(1 for x in v if x > 0) / len(v) * 100
        print(f"  {lo:>3}~{hi:<3}% {len(v):>9} {statistics.mean(v):>+9.3f}% {w:>7.1f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
