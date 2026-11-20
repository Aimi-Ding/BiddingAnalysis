import puppeteer from 'puppeteer-core';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const URL = 'http://127.0.0.1:8899/index.html';

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000 });

const errors = [];
const consoleErr = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', m => { if (m.type() === 'error') consoleErr.push(m.text()); });

await page.goto(URL, { waitUntil: 'networkidle2', timeout: 45000 });
await new Promise(r => setTimeout(r, 3500));

// 直接读 IndexedDB
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

const panel = await page.evaluate(() => {
  const p = document.getElementById('snapPanel');
  return p ? {
    visible: getComputedStyle(p).display !== 'none',
    days: document.getElementById('snapDays')?.textContent,
    state: document.getElementById('snapState')?.textContent,
    hint: document.getElementById('snapHint')?.textContent,
  } : null;
});

// 先清空，保证测的是本次抓取
await page.evaluate(() => new Promise((resolve) => {
  const req = indexedDB.open('auction_snapshots', 1);
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

// 点「立即抓取」
await page.click('#snapNowBtn');
await new Promise(r => setTimeout(r, 9000));

const after = await readIdb();
const uiAfter = await page.evaluate(() => ({
  days: document.getElementById('snapDays')?.textContent,
  last: document.getElementById('snapLast')?.textContent,
  state: document.getElementById('snapState')?.textContent,
  hint: document.getElementById('snapHint')?.textContent,
}));

const d = after[0] || null;
console.log(JSON.stringify({
  errors,
  consoleErr: consoleErr.filter(x => !/favicon|404/.test(x)),
  panel,
  beforeCount: before.length,
  afterCount: after.length,
  record: d ? {
    date: d.date, time: d.t, quality: d.q, count: d.n,
    first3: (d.rows || []).slice(0, 3),
  } : null,
  uiAfter,
}, null, 2));

await browser.close();
