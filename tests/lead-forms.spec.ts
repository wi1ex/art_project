import { test, expect, type Page } from '@playwright/test';

type LeadRequest = { phone: string; consent: boolean; request_id: string; website: string };
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const leadForm = (page: Page, variant: 'contact' | 'footer') => page.locator(`[data-lead-form][data-lead-variant="${variant}"]`);

test.beforeEach(async ({ page }) => {
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', accepting_leads: true } }));
});

test('one availability request enables both lead forms after each page initialization', async ({ page }) => {
  let healthRequests = 0;
  await page.route('**/api/healthz', route => {
    healthRequests++;
    return route.fulfill({ json: { status: 'ok', accepting_leads: true } });
  });
  await page.goto('/en/');
  await expect(page.locator('[data-lead-form]')).toHaveCount(2);
  for (const variant of ['contact', 'footer'] as const) {
    await expect(leadForm(page, variant).locator('[name="phone"]')).toBeEnabled();
    await expect(leadForm(page, variant).locator('[name="consent"]')).toBeEnabled();
    await expect(leadForm(page, variant).locator('button[type="submit"]')).toBeEnabled();
  }
  expect(healthRequests).toBe(1);

  await page.locator('.languages a[lang="cs"]').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'cs');
  for (const variant of ['contact', 'footer'] as const) {
    await expect(leadForm(page, variant).locator('[name="phone"]')).toBeEnabled();
    await expect(leadForm(page, variant).locator('button[type="submit"]')).toBeEnabled();
  }
  expect(healthRequests).toBe(2);
});

test('the footer form has unique accessible fields and sends the normalized lead payload', async ({ page }) => {
  const requests: LeadRequest[] = [];
  await page.route('**/api/leads', async route => {
    const body = route.request().postDataJSON() as LeadRequest;
    requests.push(body);
    await route.fulfill({ status: 202, json: { status: 'accepted', request_id: body.request_id } });
  });
  await page.goto('/en/');
  const footer = leadForm(page, 'footer');
  await expect(footer.locator('[name="phone"]')).toBeEnabled();
  for (const id of ['phone', 'form-status', 'lead-website', 'footer-phone', 'footer-form-status', 'footer-lead-website']) {
    await expect(page.locator(`[id="${id}"]`)).toHaveCount(1);
  }
  await expect(footer).toHaveAttribute('aria-describedby', 'footer-form-status');
  await expect(footer.getByRole('textbox', { name: 'Phone', exact: true })).toHaveAttribute('aria-describedby', 'footer-form-status');
  await expect(footer.getByRole('button', { name: 'Call me', exact: true })).toHaveAttribute('title', 'Call me');
  await footer.getByRole('textbox', { name: 'Phone', exact: true }).fill('+420 (774) 411-158');
  await footer.locator('[name="consent"]').check();
  await footer.getByRole('button', { name: 'Call me', exact: true }).click();
  await expect(footer.locator('[role="status"]')).toHaveText('Your request has been accepted. We will contact you at the phone number provided.');
  await expect(footer.locator('[role="status"]')).toHaveAttribute('aria-live', 'polite');
  await expect(footer.locator('button[type="submit"]')).toBeDisabled();
  expect(requests).toEqual([{
    phone: '+420774411158', consent: true, website: '', request_id: expect.stringMatching(uuidPattern),
  }]);
});

test('a phone being submitted or accepted in one form cannot be sent again from the other', async ({ page }) => {
  const requests: LeadRequest[] = [];
  let releaseResponse = () => {};
  const responseGate = new Promise<void>(resolve => { releaseResponse = resolve; });
  await page.route('**/api/leads', async route => {
    const body = route.request().postDataJSON() as LeadRequest;
    requests.push(body);
    await responseGate;
    await route.fulfill({ status: 202, json: { status: 'accepted', request_id: body.request_id } });
  });
  await page.goto('/en/');
  const contact = leadForm(page, 'contact');
  const footer = leadForm(page, 'footer');
  for (const form of [contact, footer]) {
    await expect(form.locator('[name="phone"]')).toBeEnabled();
    await form.locator('[name="phone"]').fill('+420774411158');
    await form.locator('[name="consent"]').check();
  }
  try {
    await contact.locator('button[type="submit"]').click();
    await expect.poll(() => requests.length).toBe(1);
    await expect(footer.locator('button[type="submit"]')).toBeDisabled();
    await expect(footer.locator('[role="status"]')).toHaveAttribute('data-state', 'pending');
    await footer.evaluate(form => (form as HTMLFormElement).requestSubmit());
    expect(requests).toHaveLength(1);
  } finally {
    releaseResponse();
  }
  await expect(contact.locator('[role="status"]')).toHaveAttribute('data-state', 'success');
  await expect(footer.locator('[role="status"]')).toHaveAttribute('data-state', 'success');
  await expect(footer.locator('button[type="submit"]')).toBeDisabled();
  await footer.evaluate(form => (form as HTMLFormElement).requestSubmit());
  expect(requests).toHaveLength(1);
  await footer.locator('[name="phone"]').fill('+420774411159');
  await expect(footer.locator('button[type="submit"]')).toBeEnabled();
});

test('an uncertain footer request retains its UUID when retried after a language change', async ({ page }) => {
  const requests: LeadRequest[] = [];
  await page.route('**/api/leads', async route => {
    const body = route.request().postDataJSON() as LeadRequest;
    requests.push(body);
    if (requests.length === 1) {
      await route.abort('connectionfailed');
      return;
    }
    await route.fulfill({ status: 200, json: { status: 'accepted', request_id: body.request_id } });
  });
  await page.goto('/ru/');
  const footer = leadForm(page, 'footer');
  await expect(footer.locator('[name="phone"]')).toBeEnabled();
  await footer.locator('[name="phone"]').fill('+420 (774) 411-158');
  await footer.locator('[name="consent"]').check();
  await footer.locator('button[type="submit"]').click();
  await expect(footer.locator('[role="status"]')).toContainText('Не удалось подтвердить приём заявки');
  await expect(footer.locator('button[type="submit"]')).toBeEnabled();
  expect(requests).toHaveLength(1);
  const initialTimeOrigin = await page.evaluate(() => performance.timeOrigin);

  await page.locator('.languages a[lang="cs"]').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'cs');
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(initialTimeOrigin);
  await expect(footer.locator('[name="phone"]')).toBeEnabled();
  await footer.locator('[name="phone"]').fill('+420774411158');
  await footer.locator('[name="consent"]').check();
  await footer.locator('button[type="submit"]').click();
  await expect(footer.locator('[role="status"]')).toHaveText('Poptávka byla přijata. Kontaktujeme vás na uvedeném telefonním čísle.');
  expect(requests).toHaveLength(2);
  expect(requests[0].request_id).toMatch(uuidPattern);
  expect(requests[1]).toEqual(requests[0]);
});
