const { test, expect } = require('@playwright/test');

async function openCinemaMenu(page) {
  const toggle = page.locator('#mobileMenuToggle');
  if (await toggle.isVisible()) {
    await toggle.click();
    await expect(page.locator('#cinemaNav')).toHaveClass(/open/);
  }
}

function escapeForRegex(value) {
  return value.replace(/[.*+?^$()|[\]\\]/g, '\\$&');
}

async function clickCinemaMenu(page, label, expectedHash) {
  await openCinemaMenu(page);
  const button = page.locator('.cinema-nav-item').filter({ hasText: label }).first();
  await expect(button).toBeVisible();
  await button.click();
  await expect(page).toHaveURL(new RegExp(escapeForRegex(expectedHash) + '$'));
}

test.beforeEach(async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page._videoLibraryPageErrors = errors;

  await page.goto('/');
  await expect(page.locator('#headerBrandReset')).toBeVisible();
  await expect(page.locator('#catalogCount')).toHaveText(/12\s*作品/);
  await expect(page.locator('.card').first()).toBeVisible();
});

test.afterEach(async ({ page }) => {
  expect(
    page._videoLibraryPageErrors,
    'browser pageerror must stay empty'
  ).toEqual([]);
});

test('initial view starts at the header and renders the catalog', async ({ page }) => {
  await expect(page.locator('#headerBrandReset')).toContainText('関町北映画館');
  await expect(page.locator('#catalog')).toBeVisible();
  await expect(page.locator('.card')).toHaveCount(12);
  await expect(page.locator('#categories')).toContainText('テスト');

  await expect.poll(async () => page.evaluate(() => window.scrollY)).toBe(0);
});

test('all five cinema navigation items work', async ({ page }) => {
  await clickCinemaMenu(page, '上映中', '#/home/continue');
  await expect(page.locator('#catalog')).toBeVisible();

  await clickCinemaMenu(page, '次回上映', '#/home/next');
  await expect(page.locator('#catalog')).toBeVisible();

  await clickCinemaMenu(page, '作品目録', '#/library');
  await expect(page.locator('.card').first()).toBeVisible();

  await clickCinemaMenu(page, '監督／演出', '#/people/directors');
  await expect(page.locator('#peopleDirectory')).toBeVisible();
  await expect(page.locator('#peopleDirectoryTitle')).toHaveText('監督／演出');
  await expect(page.locator('.people-card').first()).toContainText('テスト監督');

  await clickCinemaMenu(page, '主な出演者／声優', '#/people/cast');
  await expect(page.locator('#peopleDirectory')).toBeVisible();
  await expect(page.locator('#peopleDirectoryTitle')).toHaveText('主な出演者／声優');
  await expect(page.locator('.people-card').first()).toContainText('テスト出演者');
});

test('cast directory shows profile photos, fallback, and opens person works', async ({ page }) => {
  await clickCinemaMenu(page, '主な出演者／声優', '#/people/cast');

  const pictured = page.locator('.people-card-profile').filter({ hasText: 'テスト出演者' }).first();
  await expect(pictured).toBeVisible();
  const profile = pictured.locator('.people-profile-media img');
  await expect(profile).toBeVisible();
  await expect.poll(async () => profile.evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  await expect(profile).toHaveAttribute('src', /\/tmdb-person-image\/9001/);

  const fallback = page.locator('.people-card-profile').filter({ hasText: '写真なし出演者' }).first();
  await expect(fallback).toBeVisible();
  await expect(fallback.locator('.people-profile-fallback')).toBeVisible();

  await pictured.click();
  await expect(page).toHaveURL(/#\/person\//);
  await expect(page.locator('#message')).toContainText('テスト出演者');
  await expect(page.locator('.card').first()).toBeVisible();
});

test('director directory shows profile photos, fallback, and opens person works', async ({ page }) => {
  await clickCinemaMenu(page, '監督／演出', '#/people/directors');

  const pictured = page.locator('.people-card-profile').filter({ hasText: 'テスト監督' }).first();
  await expect(pictured).toBeVisible();
  const profile = pictured.locator('.people-profile-media img');
  await expect(profile).toBeVisible();
  await expect.poll(async () => profile.evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  await expect(profile).toHaveAttribute('src', /\/tmdb-person-image\/9002/);

  const fallback = page.locator('.people-card-profile').filter({ hasText: '写真なし監督' }).first();
  await expect(fallback).toBeVisible();
  await expect(fallback.locator('.people-profile-fallback')).toBeVisible();

  await pictured.click();
  await expect(page).toHaveURL(/#\/person\//);
  await expect(page.locator('#message')).toContainText('テスト監督');
  await expect(page.locator('.card').first()).toBeVisible();
});

test('work cards open the work detail screen', async ({ page }) => {
  const firstCard = page.locator('.card').first();
  await expect(firstCard).toContainText('テスト作品001');
  await firstCard.click();

  await expect(page).toHaveURL(/#\/work\/\d+$/);
  await expect(page.locator('#detail')).toBeVisible();
  await expect(page.locator('#workDetail')).toContainText('テスト作品001');
  await expect(page.locator('#back')).toBeVisible();
});

test('responsive shell matches PC, Tablet, and Smartphone behavior', async ({ page }, testInfo) => {
  const project = testInfo.project.name;
  const header = page.locator('header');
  const brand = page.locator('#headerBrandReset');
  const nav = page.locator('#cinemaNav');
  const toggle = page.locator('#mobileMenuToggle');

  const [headerBox, brandBox] = await Promise.all([header.boundingBox(), brand.boundingBox()]);
  expect(headerBox).not.toBeNull();
  expect(brandBox).not.toBeNull();
  const headerCenter = headerBox.x + headerBox.width / 2;
  const brandCenter = brandBox.x + brandBox.width / 2;
  expect(Math.abs(headerCenter - brandCenter)).toBeLessThanOrEqual(3);

  const noHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1
  );
  expect(noHorizontalOverflow).toBeTruthy();

  if (project === 'PC') {
    await expect(nav).toBeVisible();
    await expect(toggle).toBeHidden();
  } else {
    await expect(toggle).toBeVisible();
    await expect(nav).not.toHaveClass(/open/);
    await toggle.click();
    await expect(nav).toHaveClass(/open/);
    await expect(page.locator('.cinema-nav-item')).toHaveCount(5);
  }
});
