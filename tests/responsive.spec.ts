import { test, expect, type Page } from '@playwright/test';

const desktopWidths = [1000, 1024, 1280, 1440, 1600, 1919];
const selectors = [
  '.header', '.hero', '.hero-copy', 'h1', '.service-grid', '.service-grid li',
  '.principles', '.principles li', '.contact', '.contact-form',
  '.site-footer', '.footer-grid', '.footer-bottom',
] as const;

async function geometry(page: Page) {
  // Compare completed layouts rather than the asynchronous health-check label.
  await expect(page.locator('#contact [role="status"]')).toHaveAttribute('data-state', 'error');
  await page.evaluate(() => document.fonts.ready);
  return page.evaluate(selectors => {
    const canvas = document.querySelector<HTMLElement>('.site-canvas')!;
    const bounds = canvas.getBoundingClientRect();
    const scale = bounds.width / 1920;
    const elements = Object.fromEntries(selectors.map(selector => {
      const element = document.querySelector<HTMLElement>(selector)!;
      const rect = element.getBoundingClientRect();
      return [selector, {
        x: (rect.left - bounds.left) / scale,
        y: (rect.top - bounds.top) / scale,
        width: rect.width / scale,
        height: rect.height / scale,
        layoutWidth: element.offsetWidth,
        layoutHeight: element.offsetHeight,
      }];
    }));
    return { elements, scale, canvasHeight: bounds.height / scale, canvasWidth: bounds.width,
      canvasLeft: bounds.left, availableWidth: document.body.getBoundingClientRect().width,
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth };
  }, selectors);
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: false } }));
});

for (const lang of ['cs', 'en', 'ru']) {
  test(`${lang}: intermediate desktop widths retain the complete 1920px composition`, async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1000 });
    await page.goto(`/${lang}/`);
    const reference = await geometry(page);
    expect(reference.scale).toBeCloseTo(Math.min(1, reference.availableWidth / 1920), 3);

    for (const width of desktopWidths) {
      await page.setViewportSize({ width, height: 1000 });
      const current = await geometry(page);
      expect(current.canvasWidth, `${width}px canvas`).toBeCloseTo(current.availableWidth, 1);
      expect(current.documentWidth, `${width}px document`).toBeLessThanOrEqual(current.viewportWidth);
      expect(Math.abs(current.canvasHeight - reference.canvasHeight), `${width}px document height`).toBeLessThan(3);
      for (const selector of selectors) {
        const actual = current.elements[selector];
        const expected = reference.elements[selector];
        for (const property of ['x', 'y', 'width', 'height', 'layoutWidth', 'layoutHeight'] as const) {
          const difference = Math.abs(actual[property] - expected[property]);
          const label = `${width}px ${selector} ${property}`;
          if (property === 'layoutWidth' || property === 'layoutHeight') {
            // Zoom rasterizes 1px borders to a device pixel, then offset* rounds
            // the logical result to an integer. Keep rendered geometry stricter.
            expect(difference, label).toBeLessThanOrEqual(2);
          } else {
            expect(difference, label).toBeLessThan(2);
          }
        }
      }
      await expect(page.locator('.desktop-nav')).toBeVisible();
      await expect(page.locator('[data-menu-open]')).not.toBeVisible();
    }
  });
}

test('screens wider than 1920px keep the desktop canvas centered at its original size', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1000 });
  await page.goto('/cs/');
  const reference = await geometry(page);
  await page.setViewportSize({ width: 2560, height: 1000 });
  const wide = await geometry(page);
  expect(wide.canvasWidth).toBeCloseTo(1920, 1);
  expect(wide.scale).toBeCloseTo(1, 3);
  expect(wide.canvasLeft).toBeCloseTo((wide.availableWidth - 1920) / 2, 1);
  expect(wide.documentWidth).toBeLessThanOrEqual(wide.viewportWidth);
  for (const selector of selectors) {
    expect(wide.elements[selector]).toEqual(reference.elements[selector]);
  }
});

test('999px is fully mobile and 1000px switches all components to desktop', async ({ page }) => {
  await page.setViewportSize({ width: 999, height: 900 });
  await page.goto('/cs/');
  await expect(page.locator('[data-menu-open]')).toBeVisible();
  await expect(page.locator('.desktop-nav')).not.toBeVisible();
  await expect(page.locator('.languages')).not.toBeVisible();
  await expect(page.locator('.comparison-range')).toHaveCSS('writing-mode', 'vertical-lr');
  expect(await page.locator('.hero-image').evaluate(image => (image as HTMLImageElement).currentSrc)).toContain('hero-mobile.webp');
  expect(await page.locator('.principles').evaluate(element => getComputedStyle(element).display)).toBe('flex');
  expect(await page.locator('.contact').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(1);
  await page.locator('[data-menu-open]').click();
  await expect(page.locator('#mobile-menu-panel')).toBeVisible();

  await page.setViewportSize({ width: 1000, height: 900 });
  await expect(page.locator('#mobile-menu-panel')).not.toBeVisible();
  await expect(page.locator('[data-menu-open]')).not.toBeVisible();
  await expect(page.locator('.desktop-nav')).toBeVisible();
  await expect(page.locator('.languages')).toBeVisible();
  await expect(page.locator('.comparison-range')).toHaveCSS('writing-mode', 'horizontal-tb');
  await expect.poll(() => page.locator('.hero-image').evaluate(image => (image as HTMLImageElement).currentSrc)).toContain('/images/hero.webp');
  expect(await page.locator('.principles').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(3);
  expect(await page.locator('.contact').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(2);
});

test('a classic scrollbar and the CSS zoom fallback fit the available content width', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 900 });
  await page.goto('/en/');
  await page.addStyleTag({ content: `
    html { overflow-y: scroll; scrollbar-gutter: stable; }
    ::-webkit-scrollbar { width: 16px; }
    .site-canvas { zoom: min(1, tan(atan2(100cqw, 1920px))) !important; }
  ` });
  const reference = await geometry(page);
  for (const width of [1000, 1280, 1919]) {
    await page.setViewportSize({ width, height: 900 });
    const current = await geometry(page);
    expect(current.canvasWidth).toBeCloseTo(current.availableWidth, 1);
    expect(current.documentWidth).toBeLessThanOrEqual(current.viewportWidth);
    for (const selector of ['.header', '.hero', '.principles', '.contact', '.footer-grid']) {
      for (const property of ['x', 'y', 'width', 'height'] as const) {
        expect(Math.abs(current.elements[selector][property] - reference.elements[selector][property]), `${width}px ${selector} ${property}`).toBeLessThan(2);
      }
    }
  }
});

test('the scaled desktop service carousel uses a complete logical card step', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.goto('/en/');
  const step = await page.locator('#service-list').evaluate(list => {
    const card = list.querySelector('li')!;
    return card.offsetWidth + parseFloat(getComputedStyle(list).columnGap);
  });
  const next = page.locator('[data-carousel-controls] [data-slide="1"]');
  await next.focus();
  await expect(next).toBeFocused();
  await page.keyboard.press('Enter');
  await expect.poll(async () => Math.abs((await page.locator('#service-list').evaluate(list => list.scrollLeft)) - step)).toBeLessThan(2);
  const previous = page.locator('[data-carousel-controls] [data-slide="-1"]');
  await previous.click();
  await expect.poll(() => page.locator('#service-list').evaluate(list => list.scrollLeft)).toBeLessThan(2);
  await previous.click();
  await expect(page.locator('#service-list li').last()).toBeInViewport();
});

test('scaled desktop inputs receive pointer and keyboard interaction at their visible positions', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: true } }));
  await page.route('**/api/leads', route => route.fulfill({
    status: 202, json: { status: 'accepted', request_id: route.request().postDataJSON().request_id },
  }));
  await page.goto('/en/');
  const range = page.locator('.comparison-range');
  await range.focus();
  await page.keyboard.press('ArrowRight');
  await expect(range).toHaveValue('51');

  const phone = page.locator('#contact [name="phone"]');
  await expect(phone).toBeEnabled();
  await phone.scrollIntoViewIfNeeded();
  const bounds = (await phone.boundingBox())!;
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await expect(phone).toBeFocused();
  await page.keyboard.type('+420777123456');
  await page.locator('#contact [name="consent"]').check();
  const submitted = page.waitForRequest(request => request.url().endsWith('/api/leads'));
  await page.locator('#contact button[type="submit"]').click();
  expect((await submitted).postDataJSON()).toMatchObject({ phone: '+420777123456', consent: true });
  await expect(page.locator('#contact [role="status"]')).toHaveAttribute('data-state', 'success');
});
