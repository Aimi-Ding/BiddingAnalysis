// 用同一批真实行情，跑「改前」和「改后」两套选股逻辑，量化差异。
const API = 'https://push2dycalc.eastmoney.com/api/qt/clist/get?fs=m:1+t:2,m:0+t:6,m:0+t:80&fltt=2&invt=2'
  + '&fields=f2,f3,f4,f5,f6,f10,f12,f14,f18,f20,f21,f615,f630,f100,f102,f103&fid=f3&po=1&pn=1&pz=100&np=1';

const num = (v, d = 0) => { const n = Number(v); return Number.isFinite(n) ? n : d; };
const clamp01 = x => Math.min(Math.max(Number.isFinite(x) ? x : 0, 0), 1);

// ---------- 改前（原版） ----------
// 关键：原版请求的 fields 里没有 f6/f18/f20/f21，这些字段拿到的是 undefined。
// 为了让「改前」真实复现原版行为，先剥掉这几个字段再喂给旧算法。
const oldView = s => {
  const c = { ...s };
  delete c.f6; delete c.f18; delete c.f20; delete c.f21;
  return c;
};
const oldBid = s => (s.f615 !== undefined ? s.f615 : (s.f3 || 0));
const oldYest = s => {
  const cur = s.f4 || 0, prev = s.f2 || 0;
  return prev === 0 ? 0 : ((cur - prev) / prev) * 100;
};
const oldEligibleTop = s => {
  const n = s.f14 || '';
  if (n.includes('ST') || n.includes('*ST')) return false;
  if ((s.f4 || 0) <= 0 || (s.f5 || 0) === 0) return false;
  if (oldYest(s) >= 9.5) return false;
  if (oldBid(s) >= 7) return false;
  return true;
};
const oldScoreTop = s => {
  const bid = oldBid(s), real = s.f3 || 0, warn = s.f630 || 0;
  const amount = s.f20 || 0;                 // 原版：未请求的字段
  const vr = s.f10 || 1;
  let bve = (s.f5 || 0) * Math.min(Math.max(bid / 6, 0.2), 1.5);
  bve = Math.min(bve, 500000);
  const nBid = clamp01(bid / 8), nReal = clamp01(real / 9);
  const w = warn === 5 ? 1.0 : warn === 4 ? 0.85 : 0.3;
  const nAmt = clamp01(Math.log10(amount + 1) / 9);
  const nVR = clamp01(vr / 8), nVE = clamp01(Math.log10(bve + 1) / 5.5);
  const total = nBid * 0.32 + nReal * 0.22 + w * 0.16 + nAmt * 0.12 + nVR * 0.08 + nVE * 0.10;
  return Math.round(clamp01(total) * 100);
};

// ---------- 改后（新版） ----------
const getBid = s => { const v = num(s.f615, NaN); return Number.isFinite(v) ? v : num(s.f3); };
const prevClose = s => {
  const d = num(s.f18, NaN);
  if (Number.isFinite(d) && d > 0) return d;
  const b = num(s.f2) - num(s.f4);
  return b > 0 ? b : 0;
};
const getToday = s => { const p = prevClose(s); return p <= 0 ? 0 : ((num(s.f2) - p) / p) * 100; };
const isYestLimitUp = s => {
  const c = String(s.f103 || '');
  return c.includes('昨日涨停') || c.includes('昨日首板');
};
const newEligibleTop = s => {
  const n = String(s.f14 || '');
  if (n.includes('ST')) return false;
  if (num(s.f4) <= 0 || num(s.f5) === 0) return false;
  if (isYestLimitUp(s)) return false;
  if (getBid(s) >= 7) return false;
  return true;
};
const newScoreTop = s => {
  const bid = getBid(s), today = num(s.f3), warn = num(s.f630);
  const amount = num(s.f6), vr = num(s.f10);
  let bve = num(s.f5) * Math.min(Math.max(bid / 6, 0.2), 1.5);
  bve = Math.min(bve, 500000);
  const nBid = clamp01(bid / 8), nToday = clamp01(today / 9);
  const w = warn === 5 ? 1.0 : warn === 4 ? 0.85 : 0.3;
  const nAmt = clamp01(Math.log10(amount + 1) / 9);
  const nVR = clamp01(vr / 8), nVE = clamp01(Math.log10(bve + 1) / 5.5);
  const total = nBid * 0.32 + nToday * 0.22 + w * 0.16 + nAmt * 0.12 + nVR * 0.08 + nVE * 0.10;
  return Math.round(clamp01(total) * 100);
};

// 右侧：改前 vs 改后
const oldScoreBot = s => {
  const bid = oldBid(s), warn = s.f630 || 0, yest = oldYest(s);
  const cmv = s.f10 || 0;              // 原版把量比当流通市值
  const bv = s.f5 || 0;
  let rv = 0.3;
  if (cmv > 0) { const r = bv / (cmv / 10000); rv = r >= 3 ? 1 : r >= 2 ? 0.9 : r >= 1 ? 0.75 : r >= 0.5 ? 0.55 : 0.3; }
  const w = warn === 5 ? 1 : warn === 4 ? 0.85 : 0.2;
  let bs = 0.1;
  if (bid >= 7 && bid <= 9) bs = 1; else if (bid >= 5) bs = 0.8; else if (bid >= 3) bs = 0.6; else if (bid >= 1) bs = 0.4; else if (bid >= 0) bs = 0.25;
  const ys = yest >= 9.5 ? 1 : yest >= 7 ? 0.7 : yest >= 3 ? 0.5 : 0.3;
  const mv = cmv < 50 ? 1 : cmv < 100 ? 0.8 : cmv < 200 ? 0.5 : 0.3;
  const base = rv * 0.3 + w * 0.2 + bs * 0.2 + ys * 0.15 + mv * 0.10;
  return Math.max(8, Math.min(96, Math.round(base * 100)));
};
const newScoreBot = s => {
  const bid = getBid(s), warn = num(s.f630), today = getToday(s);
  const cap = num(s.f21), price = num(s.f2);
  const shares = (cap > 0 && price > 0) ? cap / price : 0;
  const turnover = shares > 0 ? (num(s.f5) * 100) / shares * 100 : 0;
  let rv = 0.3;
  if (turnover >= 3) rv = 1; else if (turnover >= 2) rv = 0.9; else if (turnover >= 1) rv = 0.75; else if (turnover >= 0.5) rv = 0.55;
  const w = warn === 5 ? 1 : warn === 4 ? 0.85 : 0.2;
  let bs = 0.1;
  if (bid >= 7 && bid <= 9) bs = 1; else if (bid >= 5) bs = 0.8; else if (bid >= 3) bs = 0.6; else if (bid >= 1) bs = 0.4; else if (bid >= 0) bs = 0.25;
  const ts = today >= 9.5 ? 1 : today >= 7 ? 0.7 : today >= 3 ? 0.5 : 0.3;
  const capYi = cap / 1e8;
  const mv = capYi > 0 ? (capYi < 50 ? 1 : capYi < 100 ? 0.8 : capYi < 200 ? 0.5 : 0.3) : 0.3;
  const raw = rv * 0.30 + w * 0.20 + bs * 0.20 + ts * 0.15 + mv * 0.10;
  return Math.round(clamp01(raw / 0.95) * 100);
};

// ---------- 跑 ----------
const res = await fetch(API, { headers: { 'User-Agent': 'Mozilla/5.0' } });
const json = await res.json();
const raw = json.data.diff;
console.log(`样本：${raw.length} 只（全市场 ${json.data.total} 只中涨幅前 100）\n`);

const yestLimit = raw.filter(isYestLimitUp);
const oldPassed = raw.filter(s => oldEligibleTop(oldView(s)));
const newPassed = raw.filter(newEligibleTop);
const leak = yestLimit.filter(s => oldEligibleTop(oldView(s)));

console.log('【① 剔除「昨日涨停」是否生效】');
console.log(`  概念含「昨日涨停/昨日首板」的股票：${yestLimit.length} 只`);
console.log(`  改前被放进来（漏网）：${leak.length} 只  ${leak.map(s => s.f14).join('、') || '无'}`);
console.log(`  改后被放进来（漏网）：${newPassed.filter(isYestLimitUp).length} 只\n`);

console.log('【② 通过筛选的数量】');
console.log(`  改前：${oldPassed.length} 只`);
console.log(`  改后：${newPassed.length} 只\n`);

const oldTop = oldPassed.map(s => ({ code: s.f12, name: s.f14, score: oldScoreTop(oldView(s)) }))
  .sort((a, b) => b.score - a.score).slice(0, 5);
const newTop = newPassed.map(s => ({ code: s.f12, name: s.f14, score: newScoreTop(s) }))
  .sort((a, b) => b.score - a.score).slice(0, 5);
console.log('【③ 左侧前三：改前 vs 改后】');
console.log('  改前：', oldTop.slice(0, 3).map(x => `${x.name}(${x.score})`).join('  '));
console.log('  改后：', newTop.slice(0, 3).map(x => `${x.name}(${x.score})`).join('  '));
const maxOld = Math.max(...oldPassed.map(s => oldScoreTop(oldView(s))));
console.log(`  改前最高分：${maxOld}（amount 读 f20 而原版未请求，该项恒 0，理论上限 88）`);
console.log(`  改前样本里 f20 是否为 undefined：${oldView(raw[0]).f20 === undefined}`);
console.log(`  改后最高分：${Math.max(...newPassed.map(newScoreTop))}\n`);

const oldBotScores = newPassed.map(s => oldScoreBot(oldView(s)));
const newBotScores = newPassed.map(newScoreBot);
console.log('【④ 右侧分数区间】');
console.log(`  改前：${Math.min(...oldBotScores)} ~ ${Math.max(...oldBotScores)}（权重和 0.95，且被夹到 8~96）`);
console.log(`  改后：${Math.min(...newBotScores)} ~ ${Math.max(...newBotScores)}（归一化到 0~100）\n`);

// 右侧排序是否变了
const oldBotOrder = newPassed.map(s => ({ n: s.f14, s: oldScoreBot(oldView(s)) })).sort((a, b) => b.s - a.s).slice(0, 5);
const newBotOrder = newPassed.map(s => ({ n: s.f14, s: newScoreBot(s) })).sort((a, b) => b.s - a.s).slice(0, 5);
console.log('【⑤ 右侧前五：改前 vs 改后】');
console.log('  改前：', oldBotOrder.map(x => `${x.n}(${x.s})`).join('  '));
console.log('  改后：', newBotOrder.map(x => `${x.n}(${x.s})`).join('  '));

// 竞价换手率验证
const sample = raw.find(s => s.f12 === '300812');
if (sample) {
  const shares = num(sample.f21) / num(sample.f2);
  const t = (num(sample.f5) * 100) / shares * 100;
  console.log(`\n【⑥ 竞价换手率算法验证（300812 易天股份）】`);
  console.log(`  流通股本 = f21/f2 = ${(num(sample.f21)/1e8).toFixed(2)}亿 / ${num(sample.f2)} = ${(shares/1e8).toFixed(2)}亿股`);
  console.log(`  竞价换手率 = f5*100/流通股本 = ${t.toFixed(2)}%  （腾讯行情同时刻给的是 11.88%，可对照）`);
}
