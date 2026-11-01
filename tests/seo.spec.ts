import { test, expect } from '@playwright/test';

const origin = 'https://artprojectsro.cz';
const languages = ['cs', 'en', 'ru'] as const;
const locations = { cs: 'Praze', en: 'Prague', ru: 'Праге' };

for (const lang of languages) {
  test(`${lang}: crawlers receive localized metadata and matching company data without JavaScript`, async ({ browser, request }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    const response = await page.goto(`/${lang}/`);
    expect(response?.status()).toBe(200);
    const canonical = `${origin}/${lang}/`;
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    await expect(page).toHaveTitle(/ART PROJECT/);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /ART Project s\.r\.o\./);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /^index, follow,/);
    await expect(page.locator('h1')).toHaveCount(1);
    await expect(page.locator('h1')).toContainText(locations[lang]);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', canonical);
    for (const alternative of languages) {
      await expect(page.locator(`link[hreflang="${alternative}"]`)).toHaveAttribute('href', `${origin}/${alternative}/`);
    }
    await expect(page.locator('link[hreflang="x-default"]')).toHaveAttribute('href', `${origin}/cs/`);

    const graph = JSON.parse((await page.locator('script[type="application/ld+json"]').textContent())!)['@graph'];
    const company = graph.find((entity: { '@type': string }) => entity['@type'] === 'Electrician');
    expect(company.name).toBe('ART Project s.r.o.');
    expect(company.identifier.value).toBe('22142045');
    expect(company.address).toMatchObject({
      streetAddress: '5. května 1007/3, Nusle', addressLocality: 'Praha 4', postalCode: '140 00', addressCountry: 'CZ',
    });
    expect(company.hasOfferCatalog.itemListElement).toHaveLength(4);
    expect(company).not.toHaveProperty('aggregateRating');
    expect(company).not.toHaveProperty('openingHours');
    await expect(page.locator('footer')).toContainText(company.name);
    await expect(page.locator('footer')).toContainText(company.identifier.value);
    await expect(page.locator('footer')).toContainText(company.address.streetAddress);
    expect(graph.find((entity: { '@type': string }) => entity['@type'] === 'WebPage')).toMatchObject({ url: canonical, inLanguage: lang });

    await expect(page.locator('meta[property="og:url"]')).toHaveAttribute('content', canonical);
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute('content', 'summary_large_image');
    const image = await page.locator('meta[property="og:image"]').getAttribute('content');
    expect(image).toMatch(/^https:\/\/artprojectsro\.cz\/images\//);
    const asset = await request.get(new URL(image!).pathname);
    expect(asset.status()).toBe(200);
    expect(asset.headers()['content-type']).toMatch(/^image\//);
    await context.close();
  });
}

test('robots and sitemap expose only the canonical language pages with reciprocal alternatives', async ({ request, page }) => {
  const robots = await request.get('/robots.txt');
  expect(robots.status()).toBe(200);
  const rules = await robots.text();
  expect(rules).not.toMatch(/^Disallow:\s*\/$/m);
  expect(rules).toContain(`Sitemap: ${origin}/sitemap.xml`);
  const response = await request.get('/sitemap.xml');
  expect(response.status()).toBe(200);
  const sitemap = await response.text();
  const entries = await page.evaluate(xml => {
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    if (doc.querySelector('parsererror')) throw new Error('Sitemap XML is invalid');
    return [...doc.getElementsByTagName('url')].map(entry => ({
      url: entry.getElementsByTagName('loc')[0].textContent,
      alternatives: [...entry.getElementsByTagNameNS('http://www.w3.org/1999/xhtml', 'link')].map(link => ({
        language: link.getAttribute('hreflang'), url: link.getAttribute('href'),
      })),
    }));
  }, sitemap);
  expect(entries.map(entry => entry.url).sort()).toEqual(languages.map(lang => `${origin}/${lang}/`).sort());
  for (const entry of entries) {
    expect(entry.alternatives).toEqual([
      ...languages.map(language => ({ language, url: `${origin}/${language}/` })),
      { language: 'x-default', url: `${origin}/cs/` },
    ]);
  }
});

test('language navigation updates canonical, social metadata and structured data together', async ({ page }) => {
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: false } }));
  await page.goto('/cs/');
  for (const lang of ['en', 'ru', 'cs']) {
    await page.locator(`.languages a[lang="${lang}"]`).click();
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', `${origin}/${lang}/`);
    await expect(page.locator('meta[property="og:url"]')).toHaveAttribute('content', `${origin}/${lang}/`);
    await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(1);
    const data = JSON.parse((await page.locator('script[type="application/ld+json"]').textContent())!);
    expect(data['@graph'].find((entity: { '@type': string }) => entity['@type'] === 'WebPage').inLanguage).toBe(lang);
  }
});
