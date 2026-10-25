import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';

// Run only against the disposable, public fixture in GitHub-hosted CI.
if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted') {
  throw new Error('This browser fixture is restricted to GitHub-hosted Actions runners.');
}
const origin = 'http://127.0.0.1:8080';
await mkdir('artifacts', { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true, chromiumSandbox: true });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    return route.abort();
  });
  const response = await page.goto(origin, { waitUntil: 'networkidle', timeout: 15000 });
  assert.equal(response.status(), 200);
  assert.equal(await page.title(), 'CI smoke demo');
  await page.waitForFunction(() => document.querySelector('#version').textContent === 'demo-v1');
  await page.getByRole('button', { name: 'Increment', exact: true }).click();
  await page.getByRole('button', { name: 'Increment', exact: true }).click();
  assert.equal(await page.locator('#count').textContent(), '2');
  const health = await page.evaluate(async () => {
    const response = await fetch('/healthz');
    return { status: response.status, body: await response.json() };
  });
  assert.deepEqual(health, { status: 200, body: { status: 'ok' } });
  assert.deepEqual(errors, []);
  await page.screenshot({ path: 'artifacts/browser.png' });
  await writeFile('artifacts/browser-result.json', JSON.stringify({ status: 'passed', browser: browser.version(), checks: ['document', 'version fetch', 'two clicks', 'health fetch', 'no page errors'] }, null, 2));
} finally {
  await browser.close();
}
