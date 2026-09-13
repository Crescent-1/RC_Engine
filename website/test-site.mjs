import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW_MODULE_PATH || 'playwright');
const origin = process.env.SITE_TEST_URL || 'http://127.0.0.1:4317';
const output = resolve('../.site-publish/qa');

test('client website: content, sample, enquiries and responsive behaviour', async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, channel: process.env.PW_BROWSER_CHANNEL || 'chrome' });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    assert.equal((await page.goto(origin)).status(), 200);
    await page.evaluate(() => document.fonts.ready);
    await page.locator('#options .option').first().waitFor();
    const badLinks = await page.evaluate(() => [...document.querySelectorAll('a[href^="#"]')].filter((a) => !document.getElementById(a.hash.slice(1))).map((a) => a.hash));
    assert.deepEqual(badLinks, [], 'All section links have targets');
    for (const path of ['/css/main.css', '/js/app.js', '/assets/favicon.svg', '/assets/editorial.png', '/assets/og-image.png', '/assets/apple-touch-icon.png', '/robots.txt', '/sitemap.xml']) {
      assert.equal((await context.request.get(origin + path)).status(), 200, path);
    }
    for (const path of ['/.env', '/rc_engine.db', '/demo/data/sets.json']) {
      assert.equal((await context.request.get(origin + path)).status(), 404, 'Private project data is outside the public root');
    }
    const answers = [2, 0, 3, 1, 2, 0, 3, 1];
    for (let i = 0; i < answers.length; i++) {
      await page.locator('#options input').nth(answers[i]).check();
      await page.locator('#check-answer').click();
      assert.match(await page.locator('#feedback').innerText(), /^Correct/);
      if (i < answers.length - 1) await page.locator('#next-question').click();
    }
    assert.equal(await page.locator('#quiz-score').innerText(), '8 of 8 correct');
    await page.locator('#previous-question').click();
    assert.equal(await page.locator('#options input:checked').inputValue(), '2');
    assert.equal(await page.locator('#check-answer').isDisabled(), true);
    await page.locator('#reset-quiz').click();
    assert.equal(await page.locator('#quiz-score').innerText(), '0 of 8 checked');
    await page.locator('#options input').nth(0).check();
    await page.locator('#check-answer').click();
    assert.match(await page.locator('#feedback').innerText(), /Why A falls short/);
    await page.locator('#question-dots button').nth(6).click();
    assert.equal(await page.locator('#question-count').innerText(), '07 / 08');
    assert.equal(await page.locator('#question-dots button').count(), 8);
    await page.locator('#reset-quiz').click();
    assert.match(await page.locator('.pricing-grid').innerText(), /21 RC sets per month/);

    await page.locator('[data-interest="Mock Vault"]').click();
    assert.equal(await page.locator('#interest').inputValue(), 'Mock Vault');
    assert.equal(await page.locator('#enquiry-form').evaluate((form) => form.checkValidity()), false);
    await page.locator('[name="name"]').fill('Website QA');
    await page.locator('[name="email"]').fill('invalid-email');
    await page.locator('[name="organisation"]').fill('Example Institute');
    assert.equal(await page.locator('#enquiry-form').evaluate((form) => form.checkValidity()), false);
    await page.locator('[name="email"]').fill('qa@example.test');
    await page.locator('[name="brief"]').fill('40 RC sets & faculty review <sample>');
    await page.locator('#enquiry-form button[type="submit"]').click();
    assert.equal(await page.locator('#enquiry-result').isVisible(), true);
    assert.match(await page.locator('#prepared-brief').inputValue(), /40 RC sets & faculty review <sample>/);
    assert.match(await page.locator('#prepared-brief').inputValue(), /Mock Vault/);
    assert.equal(await page.locator('#enquiry-result script').count(), 0);
    const waLinks = await page.evaluate(() => [...document.querySelectorAll('a[href^="https://wa.me/"]')].map((a) => a.href));
    assert.ok(waLinks.length >= 3 && waLinks.every((h) => h.startsWith('https://wa.me/918319230930')), 'WhatsApp links use the business number');
    await page.reload();
    assert.equal(await page.locator('[name="name"]').inputValue(), '', 'Lead details are not persisted');

    await page.locator('#theme').click();
    await page.locator('.method-visual img').scrollIntoViewIfNeeded();
    await page.locator('.method-visual img').evaluate(async (img) => { await img.decode(); });
    assert.equal(await page.locator('.method-visual img').evaluate((img) => img.naturalWidth > 0), true);
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    await page.screenshot({ path: resolve(output, 'desktop-dark.png'), fullPage: true });
    await page.locator('#theme').click();
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 950 });
      await page.evaluate(() => window.scrollTo(0, 0));
      const dimensions = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
      assert.ok(dimensions.scroll <= dimensions.width + 1, `No horizontal overflow at ${width}px: ${JSON.stringify(dimensions)}`);
      await page.screenshot({ path: resolve(output, `site-${width}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.menu-toggle').click();
    assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'true');
    await page.locator('#navigation a[href="#sample"]').click();
    assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'false');
    await page.locator('.menu-toggle').click();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'false');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    const overflow = await page.evaluate(() => [...document.querySelectorAll('body *')].filter((el) => el.getBoundingClientRect().right > document.documentElement.clientWidth + 1).map((el) => el.tagName + '.' + el.className).slice(0, 12));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), 'No page overflow at 200% text size: ' + overflow.join(', '));
    await page.evaluate(() => { document.documentElement.style.fontSize = ''; window.scrollTo(0, 0); });
    await page.screenshot({ path: resolve(output, 'hero-desktop.png') });
    assert.deepEqual(errors, [], 'No uncaught browser errors');
    await context.close();
  } finally { await browser.close(); }
});
