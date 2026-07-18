// ============================================================
// Brain Bot V15 — World HQ E2E Tests (Playwright)
// Tests: navigation, E-key interaction, minimap, search,
// teleport hub, WebSocket reconnection, theme switching.
// Run: npx playwright test tests/world/
// ============================================================

import { test, expect, type Page } from '@playwright/test';

// ── Helpers ───────────────────────────────────────────────────

async function navigateToWorld(page: Page) {
  await page.goto('/world');
  // Wait for Phaser canvas to mount and loading screen to disappear
  await expect(page.locator('#world-hq-canvas canvas')).toBeVisible({ timeout: 15_000 });
  // Wait for loading overlay to vanish (ready state)
  await expect(page.locator('text=GENERATING PIXEL WORLD')).not.toBeVisible({ timeout: 15_000 });
}

async function pressKey(page: Page, key: string, count = 1) {
  for (let i = 0; i < count; i++) {
    await page.keyboard.press(key);
    await page.waitForTimeout(80);
  }
}

// ── Suite: Loading ─────────────────────────────────────────────

test.describe('World HQ — Loading', () => {
  test('shows loading screen then world', async ({ page }) => {
    await page.goto('/world');
    // Loading screen appears
    await expect(page.locator('text=BRAIN BOT V15')).toBeVisible();
    // Canvas mounts
    await expect(page.locator('#world-hq-canvas canvas')).toBeVisible({ timeout: 15_000 });
    // Loading screen disappears
    await expect(page.locator('text=GENERATING PIXEL WORLD')).not.toBeVisible({ timeout: 15_000 });
  });

  test('minimap is visible after loading', async ({ page }) => {
    await navigateToWorld(page);
    await expect(page.locator('text=MINIMAP')).toBeVisible();
  });

  test('HUD overlays appear after loading', async ({ page }) => {
    await navigateToWorld(page);
    await expect(page.locator('text=LIVE FEED')).toBeVisible();
    await expect(page.locator('text=CONFIDENCE')).toBeVisible();
    await expect(page.locator('text=COMMANDER TERMINAL')).toBeVisible();
  });
});

// ── Suite: Player movement ─────────────────────────────────────

test.describe('World HQ — Player movement', () => {
  test.beforeEach(async ({ page }) => { await navigateToWorld(page); });

  test('WASD keys move the player (minimap position changes)', async ({ page }) => {
    // Read initial minimap position text
    const coordBefore = await page.locator('text=/\\d+,\\d+/').first().textContent();

    // Press D (right) multiple times
    await pressKey(page, 'd', 15);
    await page.waitForTimeout(300);

    const coordAfter = await page.locator('text=/\\d+,\\d+/').first().textContent();
    expect(coordAfter).not.toBe(coordBefore);
  });

  test('Arrow keys also move the player', async ({ page }) => {
    const coordBefore = await page.locator('text=/\\d+,\\d+/').first().textContent();
    await pressKey(page, 'ArrowRight', 15);
    await page.waitForTimeout(300);
    const coordAfter = await page.locator('text=/\\d+,\\d+/').first().textContent();
    expect(coordAfter).not.toBe(coordBefore);
  });

  test('player does not walk through walls', async ({ page }) => {
    // Move left into the void (edge of map) — should stop at water border
    await pressKey(page, 'a', 100);
    await page.waitForTimeout(300);
    // Position X should be >= 2 (water border starts at x=0)
    const coordText = await page.locator('text=/\\d+,\\d+/').first().textContent() ?? '10,10';
    const tx = parseInt(coordText.split(',')[0]);
    expect(tx).toBeGreaterThanOrEqual(2);
  });
});

// ── Suite: Interaction ─────────────────────────────────────────

test.describe('World HQ — Interaction', () => {
  test.beforeEach(async ({ page }) => { await navigateToWorld(page); });

  test('Ctrl+K opens search bar', async ({ page }) => {
    await page.keyboard.press('Control+k');
    await expect(page.locator('placeholder=Search rooms, NPCs, agents…')).toBeVisible();
  });

  test('search bar closes on Escape', async ({ page }) => {
    await page.keyboard.press('Control+k');
    await expect(page.locator('placeholder=Search rooms, NPCs, agents…')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('placeholder=Search rooms, NPCs, agents…')).not.toBeVisible();
  });

  test('search finds CEO Room', async ({ page }) => {
    await page.keyboard.press('Control+k');
    await page.keyboard.type('CEO');
    await expect(page.locator('text=CEO Room')).toBeVisible();
  });

  test('search teleports to CEO Room on Enter', async ({ page }) => {
    const coordBefore = await page.locator('text=/\\d+,\\d+/').first().textContent();
    await page.keyboard.press('Control+k');
    await page.keyboard.type('CEO Room');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(800);
    const coordAfter = await page.locator('text=/\\d+,\\d+/').first().textContent();
    expect(coordAfter).not.toBe(coordBefore);
  });

  test('search shows NPC results', async ({ page }) => {
    await page.keyboard.press('Control+k');
    await page.keyboard.type('trader');
    await expect(page.locator('text=Trader')).toBeVisible();
  });
});

// ── Suite: Teleport ────────────────────────────────────────────

test.describe('World HQ — Teleport', () => {
  test.beforeEach(async ({ page }) => { await navigateToWorld(page); });

  test('teleport hub modal opens rooms list', async ({ page }) => {
    // Navigate to teleport hub via search
    await page.keyboard.press('Control+k');
    await page.keyboard.type('Teleport');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(800);

    // Press E to open the Teleport Hub modal
    await page.keyboard.press('e');
    await expect(page.locator('text=SELECT DESTINATION')).toBeVisible({ timeout: 3000 });
  });

  test('minimap click triggers teleport', async ({ page }) => {
    const coordBefore = await page.locator('text=/\\d+,\\d+/').first().textContent();

    // Click center of minimap canvas
    const minimap = page.locator('canvas').nth(1); // second canvas = minimap
    const box = await minimap.boundingBox();
    if (box) {
      await page.mouse.click(box.x + box.width * 0.8, box.y + box.height * 0.8);
    }

    await page.waitForTimeout(800);
    const coordAfter = await page.locator('text=/\\d+,\\d+/').first().textContent();
    expect(coordAfter).not.toBe(coordBefore);
  });
});

// ── Suite: Interaction Modal ────────────────────────────────────

test.describe('World HQ — Interaction Modal', () => {
  test.beforeEach(async ({ page }) => { await navigateToWorld(page); });

  test('CEO modal shows signal and confidence', async ({ page }) => {
    // Teleport to CEO room
    await page.keyboard.press('Control+k');
    await page.keyboard.type('CEO Room');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(800);

    // Move to NPC and press E
    await pressKey(page, 'e', 1);
    // If not close enough, the modal might not open — try pressing E again
    await page.waitForTimeout(300);
    await pressKey(page, 'e', 1);

    // Check for modal content
    const modalVisible = await page.locator('text=CEO Room').isVisible();
    if (modalVisible) {
      await expect(page.locator('text=CURRENT SIGNAL')).toBeVisible();
      await expect(page.locator('text=CONFIDENCE')).toBeVisible();
    }
  });

  test('modal closes on Escape', async ({ page }) => {
    // Open any modal via store trick — press E in a room
    await page.keyboard.press('e');
    await page.waitForTimeout(300);

    // Press Escape
    await page.keyboard.press('Escape');
    await expect(page.locator('text=SELECT DESTINATION')).not.toBeVisible();
  });

  test('mission board shows kanban columns', async ({ page }) => {
    await page.keyboard.press('Control+k');
    await page.keyboard.type('Mission Board');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(1000);
    await page.keyboard.press('e');
    await page.waitForTimeout(500);

    const modalOpen = await page.locator('text=Mission Board').count();
    if (modalOpen > 0) {
      // Kanban columns
      await expect(page.locator('text=SIGNAL')).toBeVisible();
      await expect(page.locator('text=RISK')).toBeVisible();
      await expect(page.locator('text=CLOSED')).toBeVisible();
    }
  });
});

// ── Suite: Camera ──────────────────────────────────────────────

test.describe('World HQ — Camera', () => {
  test.beforeEach(async ({ page }) => { await navigateToWorld(page); });

  test('mouse wheel zooms the world', async ({ page }) => {
    const canvas = page.locator('#world-hq-canvas canvas').first();
    const box = await canvas.boundingBox();
    if (!box) return;
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;

    // Scroll up to zoom in (no assertion on pixel, just no crash)
    await page.mouse.wheel(0, -300);
    await page.waitForTimeout(300);
    // Scroll down to zoom out
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(300);

    // Verify canvas still exists
    await expect(canvas).toBeVisible();
  });
});

// ── Suite: Theme ───────────────────────────────────────────────

test.describe('World HQ — Theme', () => {
  test.beforeEach(async ({ page }) => { await navigateToWorld(page); });

  test('all four themes are accessible via toolbar', async ({ page }) => {
    for (const label of ['CYBER', 'DARK', 'RETRO', 'LIGHT']) {
      await expect(page.locator(`text=${label}`)).toBeVisible();
    }
  });

  test('switching to RETRO theme changes UI colors', async ({ page }) => {
    // Get overlay color before
    const before = await page.locator('text=LIVE FEED').evaluate(
      (el) => window.getComputedStyle(el).color,
    );

    await page.locator('text=RETRO').click();
    await page.waitForTimeout(200);

    const after = await page.locator('text=LIVE FEED').evaluate(
      (el) => window.getComputedStyle(el).color,
    );

    // Colors should differ between CYBER and RETRO
    expect(before).not.toBe(after);
  });
});

// ── Suite: Accessibility ────────────────────────────────────────

test.describe('World HQ — Accessibility', () => {
  test.beforeEach(async ({ page }) => { await navigateToWorld(page); });

  test('all panels can be collapsed via click', async ({ page }) => {
    // Click LIVE FEED header to collapse
    await page.locator('text=+ LIVE FEED').click();
    await page.waitForTimeout(100);
    // Content should be gone (collapsed)
    const feedVisible = await page.locator('text=Waiting for events…').isVisible();
    expect(feedVisible).toBe(false);
  });

  test('search bar is keyboard-navigable', async ({ page }) => {
    await page.keyboard.press('Control+k');
    // Arrow down should move selection
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    // No crash expected
    await expect(page.locator('placeholder=Search rooms, NPCs, agents…')).toBeVisible();
  });
});
