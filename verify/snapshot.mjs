import puppeteer from 'puppeteer-core';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const URL = 'http://127.0.0.1:8899/index.html';

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1100 });

const errors = [];
const consoleErr = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', m => { if (m.type() === 'error') consoleErr.push(m.text()); });

await page.goto(URL, { waitUntil: 'networkidle2', timeout: 45000 });
await new Promise(r => setTimeout(r, 5000));

const readIdb = () => page.evaluate(() => new Promise((resolve) => {
  const req = indexedDB.open('auction_snapshots', 1);
  req.onupgradeneeded = () => {
    const db = req.result;
    if (!db.objectStoreNames.contains('days')) db.createObjectStore('days', { keyPath: 'date' });
  };
  req.onsuccess = () => {
    const db = req.result;
    if (!db.objectStoreNames.contains('days')) { db.close(); resolve([]); return; }
    const tx = db.transaction('days', 'readonly');
    const r = tx.objectStore('days').getAll();
    r.onsuccess = () => { const out = r.result || []; db.close(); resolve(out); };
    r.onerror = () => { db.close(); resolve([]); };
  };
  req.onerror = () => resolve([]);
}));

// 先清空，保证测的是本次抓取
await page.evaluate(() => new Promise((resolve) => {
  const req = indexedDB.open('auction_snapshots', 1);
  req.onupgradeneeded = () => {
    const db = req.result;
    if (!db.objectStoreNames.contains('days')) db.createObjectStore('days', { keyPath: 'date' });
  };
  req.onsuccess = () => {
    const db = req.result;
    if (!db.objectStoreNames.contains('days')) { db.close(); resolve(); return; }
    const tx = db.transaction('days', 'readwrite');
    tx.objectStore('days').clear();
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => { db.close(); resolve(); };
  };
  req.onerror = () => resolve();
}));

const before = await readIdb();

// 快照前记下主页内存里的数据
const home = await page.evaluate(() => ({
  left: (typeof cachedTop3 !== 'undefined' ? cachedTop3 : []).map(x => ({
    code: x.code, name: x.name, bid: +Number(x.bidChange).toFixed(2), score: x.score, cov: x.coverage,
  })),
  right: (typeof cachedTopList !== 'undefined' ? cachedTopList : []).map(x => ({
    code: x.code, name: x.name, bid: +Number(x.bidChange).toFixed(2),
    real: +Number(x.realChange).toFixed(2), vr: +Number(x.volumeRatio).toFixed(2),
    score: x.score, cov: x.coverage, ind: x.industry || '',
  })),
}));

await page.click('#snapNowBtn');
await new Promise(r => setTimeout(r, 7000));

const after = await readIdb();
const d = after[0] || null;
const stripRank = (arr) => (arr || []).map(({ rank, ...rest }) => rest);
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

console.log(JSON.stringify({
  errors,
  consoleErr: consoleErr.filter(x => !/favicon|404/.test(x)),
  beforeCount: before.length,
  afterCount: after.length,
  homeLeftCount: home.left.length,
  snapLeftCount: (d?.left || []).length,
  homeRightCount: home.right.length,
  snapRightCount: (d?.right || []).length,
  leftIdentical: eq(home.left, stripRank(d?.left)),
  rightIdentical: eq(home.right, stripRank(d?.right)),
  record: d ? { date: d.date, time: d.t, q: d.q } : null,
  snapLeftSample: (d?.left || []).slice(0, 3),
}, null, 2));

await browser.close();
