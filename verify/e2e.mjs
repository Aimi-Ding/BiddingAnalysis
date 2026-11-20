import puppeteer from 'puppeteer-core';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const URL = 'http://127.0.0.1:8899/index.html';

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-web-security'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000 });

const errors = [];
const consoleErrors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });

await page.goto(URL, { waitUntil: 'networkidle2', timeout: 45000 });
// 等数据渲染
await new Promise(r => setTimeout(r, 4000));

const result = await page.evaluate(() => {
  const cardArea = document.getElementById('top3CardsArea');
  const tableArea = document.getElementById('top10TableArea');
  const cards = [...document.querySelectorAll('.stock-card')].map(c => ({
    name: c.querySelector('.stock-name')?.textContent?.trim(),
    code: c.querySelector('.stock-code')?.textContent?.trim(),
    score: c.querySelector('.prob-value')?.textContent?.trim(),
    label: c.querySelector('.prob-label')?.textContent?.trim(),
    bid: c.querySelector('.bid-change')?.textContent?.trim(),
    info: c.querySelector('.info-row')?.textContent?.replace(/\s+/g, ' ').trim(),
  }));
  const headers = [...document.querySelectorAll('.stock-table thead th')].map(t => t.textContent.trim());
  const rows = [...document.querySelectorAll('.stock-table tbody tr')].slice(0, 5).map(tr => {
    const td = [...tr.querySelectorAll('td')].map(x => x.textContent.trim());
    return td;
  });
  return {
    cardTitle: document.querySelector('.dominant-title')?.textContent?.trim(),
    cardAreaText: cardArea?.textContent?.replace(/\s+/g, ' ').slice(0, 200),
    tableAreaText: tableArea?.textContent?.replace(/\s+/g, ' ').slice(0, 120),
    cards, headers, rows,
    hasLimitUpText: document.body.innerText.includes('涨停率'),
    hasAiText: document.body.innerText.includes('AI智能研判') || document.body.innerText.includes('AI多维模型'),
    cachedTop3Len: typeof cachedTop3 !== 'undefined' ? cachedTop3.length : -1,
    cachedListLen: typeof cachedTopList !== 'undefined' ? cachedTopList.length : -1,
    sampleTop3: typeof cachedTop3 !== 'undefined' ? cachedTop3.map(x => ({ code: x.code, score: x.score, cov: x.coverage })) : [],
    sampleScores: typeof cachedTopList !== 'undefined' ? cachedTopList.slice(0, 8).map(x => x.score) : [],
    allScoresInRange: typeof cachedTopList !== 'undefined'
      ? cachedTopList.every(x => x.score >= 0 && x.score <= 100) : null,
  };
});

console.log(JSON.stringify({ errors, consoleErrors, ...result }, null, 2));
await browser.close();
