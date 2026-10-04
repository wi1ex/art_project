import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: false } }));
});

for (const [region, lang] of [['CZ', 'cs'], ['RU', 'ru'], ['other', 'en']]) {
  test(`root entry follows the locale API for ${region}`, async ({ page }) => {
    let localeRequests = 0;
    await page.route('**/api/locale', route => {
      localeRequests++;
      return route.fulfill({ json: { lang } });
    });
    await page.goto('/?source=campaign');
    await expect(page).toHaveURL(new RegExp(`/${lang}/\\?source=campaign$`));
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    expect(localeRequests).toBe(1);
    expect(await page.evaluate(() => localStorage.getItem('art-project-language'))).toBeNull();
    expect(await page.locator('.languages a').evaluateAll(links => links.map(link => link.getAttribute('lang')))).toEqual(['cs', 'en', 'ru']);
    expect(await page.locator('.footer-grid a[lang]').evaluateAll(links => links.map(link => link.getAttribute('lang')))).toEqual(['cs', 'en', 'ru']);
    await expect(page.locator('.footer-bottom .geo-attribution')).toHaveAttribute('href', 'https://db-ip.com');
  });
}

test('root entry uses the saved manual language without a locale request', async ({ page }) => {
  let localeRequests = 0;
  await page.addInitScript(() => localStorage.setItem('art-project-language', 'cs'));
  await page.route('**/api/locale', route => {
    localeRequests++;
    return route.fulfill({ json: { lang: 'ru' } });
  });
  await page.goto('/');
  await expect(page).toHaveURL(/\/cs\/$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'cs');
  expect(localeRequests).toBe(0);
});

test('an explicit localized URL preserves its language despite a saved preference', async ({ page }) => {
  let localeRequests = 0;
  await page.addInitScript(() => localStorage.setItem('art-project-language', 'cs'));
  await page.route('**/api/locale', route => {
    localeRequests++;
    return route.fulfill({ json: { lang: 'en' } });
  });
  await page.goto('/ru/');
  await expect(page).toHaveURL(/\/ru\/$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  expect(localeRequests).toBe(0);
});

test('manual header and footer language choices persist across root entry and history', async ({ page }) => {
  let localeRequests = 0;
  await page.route('**/api/locale', route => {
    localeRequests++;
    return route.fulfill({ json: { lang: 'cs' } });
  });
  await page.goto('/');
  await expect(page).toHaveURL(/\/cs\/$/);
  const initialTimeOrigin = await page.evaluate(() => performance.timeOrigin);
  await page.locator('.languages').getByRole('link', { name: 'EN', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  expect(await page.evaluate(() => localStorage.getItem('art-project-language'))).toBe('en');
  await page.locator('.footer-grid').getByRole('link', { name: 'Русский', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(initialTimeOrigin);
  expect(await page.evaluate(() => localStorage.getItem('art-project-language'))).toBe('ru');
  await page.goBack();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  expect(await page.evaluate(() => localStorage.getItem('art-project-language'))).toBe('ru');
  await page.goto('/');
  await expect(page).toHaveURL(/\/ru\/$/);
  expect(localeRequests).toBe(1);
});

test('root entry falls back to English for invalid storage and a missing locale API', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('art-project-language', 'invalid'));
  await page.route('**/api/locale', route => route.fulfill({ status: 404, contentType: 'text/html', body: '<h1>Not found</h1>' }));
  await page.goto('/');
  await expect(page).toHaveURL(/\/en\/$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});

test('root entry limits a slow locale lookup and falls back to English', async ({ page }) => {
  await page.route('**/api/locale', async route => {
    await new Promise(resolve => setTimeout(resolve, 2000));
    await route.fulfill({ json: { lang: 'cs' } }).catch(() => {});
  });
  await page.goto('/');
  await expect(page).toHaveURL(/\/en\/$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});

test('a manual root choice takes priority over a pending locale lookup', async ({ page }) => {
  let releaseResponse = () => {};
  const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
  await page.route('**/api/locale', async route => {
    await responseGate;
    await route.fulfill({ json: { lang: 'cs' } }).catch(() => {});
  });
  await page.goto('/');
  await page.locator('main nav').getByRole('link', { name: 'Русский', exact: true }).click();
  await expect(page).toHaveURL(/\/ru\/$/);
  releaseResponse();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  expect(await page.evaluate(() => localStorage.getItem('art-project-language'))).toBe('ru');
});

test('root language links and English default remain usable without JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto('/');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('meta[http-equiv="refresh"]')).toHaveCount(0);
  expect(await page.locator('main nav a').evaluateAll(links => links.map(link => link.getAttribute('lang')))).toEqual(['cs', 'en', 'ru']);
  await expect(page.locator('.geo-attribution a')).toHaveAttribute('href', 'https://db-ip.com');
  await page.getByRole('link', { name: 'Continue in English →', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('h1')).toBeVisible();
  await context.close();
});

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
      await page.evaluate(() => document.fonts.ready);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.locator('footer').scrollIntoViewIfNeeded();
      for (const image of await page.locator('img:visible').all()) await image.scrollIntoViewIfNeeded();
      await expect.poll(() => page.locator('img:visible').evaluateAll(images => images.every(image => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0))).toBe(true);
      await expect(page.locator('[data-lead-form]')).toHaveCount(2);
      for (const form of await page.locator('[data-lead-form]').all()) {
        await expect(form.locator('button[type="submit"]')).toBeDisabled();
        await expect(form.locator('[name="phone"]')).toBeDisabled();
      }
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
  await expect(page.locator('.footer-email')).toHaveAttribute('href', 'mailto:mail@electroservice.com');
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
  await expect(page.locator('[data-lead-form]')).toHaveCount(2);
  for (const form of await page.locator('[data-lead-form]').all()) {
    await expect(form.locator('button[type="submit"]')).toBeDisabled();
    await expect(form.locator('[role="status"]')).toContainText('включите JavaScript');
  }
  await page.locator('.languages').getByRole('link', { name: 'EN' }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await context.close();
});

test('mobile comparison opens the heat pump and supports keyboard control', async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto('/en/');
  await expect(page.locator('.hero-image')).toHaveJSProperty('currentSrc', 'http://127.0.0.1:4321/images/hero-mobile.webp');
  await expect(page.locator('#service-list li').first().locator('img')).toHaveJSProperty('currentSrc', 'http://127.0.0.1:4321/images/service-electrical-mobile.webp');
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

type LeadRequest = { phone: string; consent: boolean; request_id: string; website: string };

test('lead form stays disabled when the API is absent or not accepting requests', async ({ page }) => {
  await page.goto('/en/');
  await expect(page.locator('#contact #form-status')).toContainText('temporarily unavailable');
  await expect(page.locator('#contact #phone')).toBeDisabled();
  await expect(page.locator('#contact [name="consent"]')).toBeDisabled();
  await expect(page.locator('#contact [data-lead-form] button')).toBeDisabled();
  await expect(page.locator('#contact .form-direct-contact a')).toHaveAttribute('href', 'tel:+420774411158');

  await page.route('**/api/healthz', route => route.fulfill({ status: 404, contentType: 'text/html', body: '<h1>Not found</h1>' }));
  await page.locator('.languages').getByRole('link', { name: 'RU', exact: true }).click();
  await expect(page.locator('#contact #form-status')).toContainText('временно недоступен');
  await expect(page.locator('#contact [data-lead-form] button')).toBeDisabled();
  await expect(page.locator('.telegram-link').first()).toHaveAttribute('href', 'https://t.me/+420774411158');
});

for (const [lang, success] of [
  ['ru', 'Заявка принята. Мы свяжемся с вами по указанному телефону.'],
  ['en', 'Your request has been accepted. We will contact you at the phone number provided.'],
  ['cs', 'Poptávka byla přijata. Kontaktujeme vás na uvedeném telefonním čísle.'],
]) {
  test(`${lang}: lead form validates and sends only a normalized phone with consent`, async ({ page }) => {
    const requests: LeadRequest[] = [];
    await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: true } }));
    await page.route('**/api/leads', async route => {
      const body = route.request().postDataJSON() as LeadRequest;
      requests.push(body);
      await route.fulfill({ status: 202, json: { status: 'accepted', request_id: body.request_id } });
    });
    await page.goto(`/${lang}/`);
    const button = page.locator('#contact [data-lead-form] button');
    await expect(button).toBeEnabled();
    await page.locator('#contact #phone').fill('774411158');
    await button.click();
    await expect(page.locator('#contact #phone')).toHaveAttribute('aria-invalid', 'true');
    expect(requests).toHaveLength(0);
    await page.locator('#contact #phone').fill('+420 (774) 411-158');
    await button.click();
    await expect(page.locator('#contact [name="consent"]')).toHaveAttribute('aria-invalid', 'true');
    expect(requests).toHaveLength(0);
    await page.locator('#contact [name="consent"]').check();
    await button.click();
    await expect(page.locator('#contact #form-status')).toHaveText(success);
    await expect(button).toBeDisabled();
    expect(requests).toHaveLength(1);
    expect(requests[0]).toEqual({
      phone: '+420774411158', consent: true, website: '',
      request_id: expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/),
    });
    await expect(page.locator('#contact #form-status')).toHaveAttribute('aria-live', 'polite');
  });
}

test('lead retries keep the request ID and pending submissions cannot repeat', async ({ page }) => {
  const requests: LeadRequest[] = [];
  let releaseResponse = () => {};
  const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: true } }));
  await page.route('**/api/leads', async route => {
    const body = route.request().postDataJSON() as LeadRequest;
    requests.push(body);
    if (requests.length === 1) { await route.abort('connectionfailed'); return; }
    if (requests.length === 2) await responseGate;
    await route.fulfill({ status: 200, json: { status: 'accepted', request_id: body.request_id } });
  });
  await page.goto('/en/');
  const button = page.locator('#contact [data-lead-form] button');
  await expect(button).toBeEnabled();
  await page.locator('#contact #phone').fill('+420774411158');
  await page.locator('#contact [name="consent"]').check();
  await button.click();
  await expect(page.locator('#contact #form-status')).toContainText('could not confirm receipt');
  await button.click();
  await expect.poll(() => requests.length).toBe(2);
  await expect(button).toBeDisabled();
  await expect(page.locator('#contact #phone')).toBeDisabled();
  await page.locator('#contact [data-lead-form]').evaluate(form => (form as HTMLFormElement).requestSubmit());
  expect(requests).toHaveLength(2);
  expect(requests[1].request_id).toBe(requests[0].request_id);
  releaseResponse();
  await expect(page.locator('#contact #form-status')).toContainText('has been accepted');
  await page.locator('#contact #phone').fill('+420774411159');
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.locator('#contact #form-status')).toContainText('has been accepted');
  expect(requests).toHaveLength(3);
  expect(requests[2].request_id).not.toBe(requests[1].request_id);
});

test('lead form respects Retry-After and remains usable after an API failure', async ({ page }) => {
  const requests: LeadRequest[] = [];
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: true } }));
  await page.route('**/api/leads', async route => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) {
      await route.fulfill({ status: 429, headers: { 'Retry-After': '1' }, json: { error: 'rate_limited' } });
    } else {
      await route.fulfill({ status: 503, json: { error: 'unavailable' } });
    }
  });
  await page.goto('/en/');
  const button = page.locator('#contact [data-lead-form] button');
  await expect(button).toBeEnabled();
  await page.locator('#contact #phone').fill('+420774411158');
  await page.locator('#contact [name="consent"]').check();
  await button.click();
  await expect(page.locator('#contact #form-status')).toContainText('Too many attempts');
  await expect(button).toBeDisabled();
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.locator('#contact #form-status')).toContainText('temporarily unavailable');
  await expect(button).toBeEnabled();
  expect(requests[1].request_id).toBe(requests[0].request_id);
});

test('language navigation ignores stale lead responses and initializes the current form', async ({ page }) => {
  let releaseResponse = () => {};
  const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
  let submitted = false;
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: true } }));
  await page.route('**/api/leads', async route => {
    const body = route.request().postDataJSON() as LeadRequest;
    submitted = true;
    await responseGate;
    await route.fulfill({ status: 202, json: { status: 'accepted', request_id: body.request_id } }).catch(() => {});
  });
  await page.goto('/ru/');
  await expect(page.locator('#contact #phone')).toBeEnabled();
  await page.locator('#contact #phone').fill('+420774411158');
  await page.locator('#contact [name="consent"]').check();
  await page.locator('#contact [data-lead-form] button').click();
  await expect.poll(() => submitted).toBe(true);
  await page.locator('.languages').getByRole('link', { name: 'CS', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'cs');
  await expect(page.locator('#contact #phone')).toBeEnabled();
  releaseResponse();
  await expect(page.locator('#contact #form-status')).toContainText('Zadejte telefon s předvolbou země');
  await expect(page.locator('#contact [data-lead-form] button')).toBeEnabled();
});
