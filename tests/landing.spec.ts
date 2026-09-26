import { test, expect } from '@playwright/test';

for (const lang of ['ru', 'en', 'cs']) {
  for (const width of [360, 430, 768, 1440, 1920]) {
    test(`${lang}: layout and assets at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      const response = await page.goto(`/${lang}/`);
      expect(response?.status()).toBe(200);
      await expect(page.locator('html')).toHaveAttribute('lang', lang);
      await expect(page.locator('h1')).toHaveCount(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.locator('footer').scrollIntoViewIfNeeded();
      for (const image of await page.locator('img:visible').all()) await image.scrollIntoViewIfNeeded();
      await expect.poll(() => page.locator('img:visible').evaluateAll(images => images.every(image => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0))).toBe(true);
      await expect(page.locator('form button')).toBeDisabled();
      expect(errors).toEqual([]);
      if (lang === 'ru' && width !== 768) {
        await page.locator('#service-list, .principles, .review-strip').evaluateAll(elements => elements.forEach(el => { el.scrollLeft = 0; }));
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
        await page.screenshot({ path: `artifacts/landing-${width}.png`, fullPage: true });
      }
    });
  }
}

test('mobile navigation and service carousel', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/en/');
  const menu = page.locator('.mobile-menu');
  await menu.locator('summary').click();
  await menu.getByRole('link', { name: 'Services', exact: true }).click();
  await expect(menu).not.toHaveAttribute('open', '');
  await page.getByRole('button', { name: 'Next service' }).click();
  await expect.poll(() => page.locator('#service-list').evaluate(el => el.scrollLeft)).toBeGreaterThan(100);
  await page.locator('.languages').getByRole('link', { name: 'CS' }).click();
  await expect(page).toHaveURL(/\/cs\/$/);
});

test('original reviews, contact links and comparison survive language changes', async ({ page }) => {
  const externalFonts: string[] = [];
  page.on('request', request => {
    if (/fonts\.(googleapis|gstatic)\.com/.test(request.url())) externalFonts.push(request.url());
  });
  await page.goto('/ru/');
  await expect(page.locator('.review-card')).toHaveCount(13);
  await expect(page.locator('.review-card')).toContainText([
    'Игорь Белов', 'Елена Морозова', 'Александр Петров', 'Марина Соколова',
  ]);
  for (const link of await page.locator('.telegram-link').all()) {
    await expect(link).toHaveAttribute('href', 'https://t.me/+420774411158');
  }
  for (const link of await page.locator('.whatsapp-link').all()) {
    await expect(link).toHaveAttribute('href', 'https://wa.me/420774411158');
  }
  for (const lang of ['ru', 'en', 'cs']) {
    if (lang !== 'ru') {
      await page.locator('.languages').getByRole('link', { name: lang.toUpperCase(), exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('lang', lang);
    }
    const slider = page.locator('#comparison-range');
    await slider.focus();
    await slider.press('End');
    await expect(slider).toHaveValue('100');
    await expect(page.locator('[data-comparison]')).toHaveCSS('--split', '100%');
    await slider.press('Home');
    await expect(slider).toHaveValue('0');
    for (let index = 1; index <= 4; index++) {
      await page.locator('[data-project-step="1"]').click();
      const scene = page.locator(`[data-scene="${index % 4}"]`);
      await expect(scene).toBeVisible();
      await expect.poll(() => scene.locator('img').evaluateAll(images => images.every(image => (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
    }
    await page.locator('[data-project-step="-1"]').click();
    await expect(page.locator('[data-scene="3"]')).toBeVisible();
  }
  expect(externalFonts).toEqual([]);
});

test('content remains available without JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto('/ru/');
  await expect(page.locator('h1')).toBeVisible();
  await expect(page.locator('#services h3')).toHaveCount(4);
  await page.locator('.languages').getByRole('link', { name: 'EN' }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await context.close();
});

test('mobile comparison opens the heat pump and supports keyboard control', async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto('/en/');
  await expect(page.locator('.hero-image')).toHaveJSProperty('currentSrc', 'http://127.0.0.1:4321/images/hero-mobile.webp');
  await expect(page.locator('[data-scene="2"]')).toBeVisible();
  const slider = page.locator('#comparison-range');
  await slider.focus();
  await slider.press('End');
  await expect(page.locator('[data-comparison]')).toHaveCSS('--split', '100%');
  await expect(slider).toHaveCSS('writing-mode', 'vertical-lr');
  await page.locator('[data-project-step="1"]').click();
  await expect(page.locator('[data-scene="3"]')).toBeVisible();
});

test('language changes keep the document alive and controls work after navigation', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/ru/');
  const initialTimeOrigin = await page.evaluate(() => performance.timeOrigin);
  const documents: string[] = [];
  page.on('request', request => { if (request.resourceType() === 'document') documents.push(request.url()); });

  for (const lang of ['en', 'cs', 'ru', 'en']) {
    await page.locator('.languages').getByRole('link', { name: lang.toUpperCase(), exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    await expect(page).toHaveURL(new RegExp(`/${lang}/$`));
    await expect(page.locator('.languages [aria-current="page"]')).toHaveText(lang.toUpperCase());
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(initialTimeOrigin);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await expect(page.locator('h1')).toContainText('Bringing construction');
  await expect(page).toHaveTitle(/engineering solutions/);
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /Electrical installation/);

  await page.goBack();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  await page.goForward();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');

  const menu = page.locator('.mobile-menu');
  await menu.locator('summary').click();
  await menu.getByRole('link', { name: 'Services', exact: true }).click();
  await expect(menu).not.toHaveAttribute('open', '');
  await page.getByRole('button', { name: 'Next service' }).click();
  await expect.poll(() => page.locator('#service-list').evaluate(el => el.scrollLeft)).toBeGreaterThan(100);
  expect(documents).toEqual([]);
});
