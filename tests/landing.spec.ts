import { test, expect } from '@playwright/test';

for (const lang of ['ru', 'en', 'cs']) {
  for (const width of [360, 768, 1440]) {
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
      for (const image of await page.locator('img').all()) await image.scrollIntoViewIfNeeded();
      await expect.poll(() => page.locator('img').evaluateAll(images => images.every(image => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0))).toBe(true);
      await expect(page.locator('form button')).toBeDisabled();
      expect(errors).toEqual([]);
      if (lang === 'ru' && width !== 768) {
        await page.locator('#service-list').evaluate(el => { el.scrollLeft = 0; });
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

test('content remains available without JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto('/ru/');
  await expect(page.locator('h1')).toBeVisible();
  await expect(page.locator('#services h3')).toHaveCount(4);
  await context.close();
});
