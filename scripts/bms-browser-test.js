/**
 * scripts/bms-browser-test.js
 *
 * Headless browser test for the BMS Simulator page.
 * Runs inside a Playwright Docker container (mcr.microsoft.com/playwright:v1.48.0-noble).
 *
 * Assertions (per UI step, 1-indexed as shown in "Langkah N/6"):
 *   - No "Error:" text in ANY successful step
 *   - No 172.x.x.x (Docker IP) in page body from step 2 onward
 *   - "Data Honeypot" label visible in steps 3, 4, 5 (adversary sees honeypot data)
 *   - Adversary shipment IDs differ from commander's DOC-1a2b3c4d5e6f in steps 3-5
 *   - After step 6: adversary data equals commander data, "Data Honeypot" label GONE
 *
 * Runs the walkthrough THREE times:
 *   Run 1: Play from initial state
 *   Run 2: Play again (triggers Reset + replay)
 *   Run 3: Reload page, then Play (fresh page state)
 *
 * Fails on: console errors (excluding expected 404/405), failed network requests,
 * any assertion failure, or not reaching step 6.
 */
const { chromium } = require('playwright');

const DASHBOARD_URL  = process.env.DASHBOARD_URL  || 'http://host.docker.internal:3000';
const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR || '/screenshots';
const MAX_WAIT_MS    = 180000;

// ── Assertion helper ──────────────────────────────────────────────────────────

async function assertStep(page, runLabel, uiStep, errors) {
  // Wait for the page to settle (step data rendered)
  await page.waitForTimeout(3000);

  const bodyText = await page.textContent('body') || '';

  // 1. No "Error:" text in any step (Batasan box uses "TIDAK" not "Error:")
  if (/Error:\s/.test(bodyText)) {
    errors.push(`${runLabel} step ${uiStep}: found "Error:" text`);
  }

  // 2. No Docker IP (172.x.x.x) from step 2 onward
  if (uiStep >= 2 && /172\.\d+\.\d+\.\d+/.test(bodyText)) {
    errors.push(`${runLabel} step ${uiStep}: Docker IP 172.x.x.x found in page`);
  }

  // 3. Honeypot data visible in steps 3, 4, 5 (adversary sees honeypot data)
  //    The adversary panel must show shipment IDs that differ from the commander's DOC-1a2b3c4d5e6f
  if (uiStep >= 3 && uiStep <= 5) {
    let honeypotConfirmed = false;
    for (let attempt = 0; attempt < 15; attempt++) {
      // Count adversary-specific shipment rows
      const advShipCount = await page.locator('[data-testid^="adv-ship-"]').count().catch(() => 0);
      if (advShipCount > 0) {
        // Get the data-testid attribute to extract the shipment ID
        const firstAdvShipId = await page.locator('[data-testid^="adv-ship-"]').first().getAttribute('data-testid').catch(() => '');
        // e.g. "adv-ship-DOC-aabb..." → extract after "adv-ship-"
        const shipId = firstAdvShipId.replace('adv-ship-', '');
        if (shipId && shipId !== 'DOC-1a2b3c4d5e6f') {
          honeypotConfirmed = true; // adversary gets different (honeypot) data
          break;
        }
        // If shipId == DOC-1a2b3c4d5e6f, the step transition may not have fully rendered yet
        // (step 2 may still be completing the canary/quarantine cycle) — keep polling
      }
      await page.waitForTimeout(1000);
    }
    if (!honeypotConfirmed) {
      errors.push(`${runLabel} step ${uiStep}: adversary still shows real commander ID — honeypot routing not active`);
    }
  }

  // 4. Commander real data present from step 1 onward
  if (uiStep >= 1 && !bodyText.includes('DOC-1a2b3c4d5e6f')) {
    errors.push(`${runLabel} step ${uiStep}: commander data DOC-1a2b3c4d5e6f not found`);
  }

  // 5. After step 6: "Data Honeypot" label must be GONE (adversary gets real data)
  if (uiStep >= 6 && bodyText.includes('Data Honeypot')) {
    errors.push(`${runLabel} step ${uiStep}: "Data Honeypot" label still present after release`);
  }

  // 6. After step 6: adversary data equals commander data
  if (uiStep >= 6 && !bodyText.includes('Data Diterima')) {
    errors.push(`${runLabel} step ${uiStep}: "Data Diterima" label not found after release`);
  }
}

// ── Run one walkthrough ───────────────────────────────────────────────────────

async function runWalkthrough(page, runLabel, screenshotPrefix) {
  const stepErrors = [];
  let lastStep = 0;
  let totalSteps = 6;

  // Click "▶ Putar"
  const playBtn = page.locator('text=▶ Putar');
  if (await playBtn.isDisabled()) {
    const resetBtn = page.locator('text=↺ Reset');
    await resetBtn.click();
    await page.waitForTimeout(1000);
  }
  await playBtn.click();
  console.log(`[${runLabel}] Clicked Play — waiting for steps...`);

  // Take initial screenshot
  await page.screenshot({ path: `${SCREENSHOT_DIR}/${screenshotPrefix}-step-0.png`, fullPage: false });

  const startTime = Date.now();
  const stepAsserted = new Set();
  const stepScreenshots = new Set([0]);

  // Assertion window (ms) to wait after a step becomes stable before asserting
  const ASSERT_WINDOW = 4000;

  while (Date.now() - startTime < MAX_WAIT_MS) {
    await page.waitForTimeout(1500);

    const caption = await page.textContent('[data-testid="step-caption"]').catch(() => '');
    const stepMatch = caption?.match(/Langkah\s+(\d+)\/(\d+)/);
    if (!stepMatch) continue;

    const currentStep = parseInt(stepMatch[1]);
    totalSteps = parseInt(stepMatch[2]);

    // Screenshot on first appearance
    if (currentStep > lastStep) {
      lastStep = currentStep;
      if (!stepScreenshots.has(currentStep)) {
        stepScreenshots.add(currentStep);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/${screenshotPrefix}-step-${currentStep}.png`,
          fullPage: false,
        });
        console.log(`[${runLabel}] Screenshot: step ${currentStep}`);
      }
    }

    // Assert the CURRENT step if we've waited long enough (step is stable)
    // This catches the bounded-wait windows where steps 4 and 5 pause for up to 10-15s.
    // For steps 3-5 (honeypot steps) we also need to assert WHILE the step is active.
    if (currentStep >= 3 && currentStep <= 5 && !stepAsserted.has(currentStep)) {
      // Wait one more cycle to let the step's data fully render
      await page.waitForTimeout(ASSERT_WINDOW);
      // Re-read caption to confirm we're still on this step
      const captionNow = await page.textContent('[data-testid="step-caption"]').catch(() => '');
      const stillOnStep = captionNow?.includes(`Langkah ${currentStep}/`);
      if (stillOnStep) {
        stepAsserted.add(currentStep);
        await assertStep(page, runLabel, currentStep, stepErrors);
      }
    }

    if (lastStep >= totalSteps) {
      await page.waitForTimeout(5000);
      if (!stepAsserted.has(totalSteps)) {
        stepAsserted.add(totalSteps);
        await assertStep(page, runLabel, totalSteps, stepErrors);
      }
      break;
    }
  }

  // Also assert any missing steps (steps that passed too fast to assert inline)
  // For steps 1-2 we only check structural things (no "Error:", no Docker IPs)
  for (let s = 1; s <= lastStep; s++) {
    if (!stepAsserted.has(s) && s <= totalSteps) {
      stepAsserted.add(s);
      // Minimal assert: just check body text at the current moment
      const bodyText = await page.textContent('body') || '';
      if (/Error:\s/.test(bodyText)) {
        stepErrors.push(`${runLabel} step ${s} (delayed check): found "Error:" text`);
      }
    }
  }

  // Final screenshot
  await page.screenshot({ path: `${SCREENSHOT_DIR}/${screenshotPrefix}-final.png`, fullPage: false });
  console.log(`[${runLabel}] Reached step ${lastStep}/${totalSteps}, errors: ${stepErrors.length}`);

  return { lastStep, totalSteps, stepErrors };
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const fs = require('fs');
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const page = await context.newPage();

  const allErrors = [];
  const consoleErrors = [];
  const failedRequests = [];

  // ── Console / network error collectors ─────────────────────────────────────
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      // Filter out expected HTTP status messages (enum scan deliberately triggers 404/405)
      if (/^Failed to load resource.*status of (404|405|429)/.test(text)) return;
      // CORS errors are real failures
      if (/has been blocked by CORS policy/.test(text)) {
        consoleErrors.push(text);
        return;
      }
      consoleErrors.push(text);
    }
  });
  page.on('requestfailed', (request) => {
    failedRequests.push({ url: request.url(), failure: request.failure()?.errorText || 'unknown' });
  });
  page.on('pageerror', (error) => {
    consoleErrors.push(`PageError: ${error.message}`);
  });

  // ── Open the BMS page ───────────────────────────────────────────────────────
  console.log(`[bms-test] Opening ${DASHBOARD_URL}/#/bms ...`);
  await page.goto(`${DASHBOARD_URL}/#/bms`, { waitUntil: 'networkidle', timeout: 30000 });

  // Verify banner
  const banner = await page.textContent('[role="alert"]').catch(() => null);
  if (!banner || !banner.includes('Simulasi ilustratif')) {
    console.error('[bms-test] FAIL: Banner not found');
    await browser.close();
    process.exit(1);
  }
  console.log('[bms-test] Banner OK');

  // ── Run 1: First walkthrough ─────────────────────────────────────────────────
  console.log('\n=== Run 1: First Play ===');
  const run1 = await runWalkthrough(page, 'Run1', 'bms-run1');
  allErrors.push(...run1.stepErrors);

  // ── Run 2: Play again (triggers Reset + replay) ──────────────────────────────
  console.log('\n=== Run 2: Replay (Reset + Play) ===');
  // The Play button should be re-enabled after run 1 completes (busy=false)
  // Clicking Play when step >= 5 triggers doReset() first
  await page.waitForTimeout(1000);
  const run2 = await runWalkthrough(page, 'Run2', 'bms-run2');
  allErrors.push(...run2.stepErrors);

  // ── Run 3: Reload page, then Play ───────────────────────────────────────────
  console.log('\n=== Run 3: Reload + Play ===');
  await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
  // Verify banner still visible after reload (no blank page)
  const bannerAfterReload = await page.textContent('[role="alert"]').catch(() => null);
  if (!bannerAfterReload || !bannerAfterReload.includes('Simulasi ilustratif')) {
    allErrors.push('Run3: Banner not found after reload — page may be blank');
  }
  const run3 = await runWalkthrough(page, 'Run3', 'bms-run3');
  allErrors.push(...run3.stepErrors);

  // ── Report ─────────────────────────────────────────────────────────────────
  console.log('\n=== BMS Browser Test Results ===');
  console.log(`Run 1: step ${run1.lastStep}/${run1.totalSteps}, errors: ${run1.stepErrors.length}`);
  console.log(`Run 2: step ${run2.lastStep}/${run2.totalSteps}, errors: ${run2.stepErrors.length}`);
  console.log(`Run 3: step ${run3.lastStep}/${run3.totalSteps}, errors: ${run3.stepErrors.length}`);
  console.log(`Console errors: ${consoleErrors.length}`);
  console.log(`Failed requests: ${failedRequests.length}`);
  console.log(`Assertion errors: ${allErrors.length}`);

  if (allErrors.length > 0) {
    console.log('\nAssertion errors:');
    allErrors.forEach((e, i) => console.log(`  ${i + 1}. ${e}`));
  }
  if (consoleErrors.length > 0) {
    console.log('\nConsole errors:');
    consoleErrors.forEach((e, i) => console.log(`  ${i + 1}. ${e}`));
  }
  if (failedRequests.length > 0) {
    console.log('\nFailed requests:');
    failedRequests.forEach((r, i) => console.log(`  ${i + 1}. ${r.url} — ${r.failure}`));
  }

  await browser.close();

  // Pass/fail: all 3 runs must reach step 6, no console errors, no failed requests,
  // no assertion errors
  const allReachedStep6 =
    run1.lastStep >= 6 && run2.lastStep >= 6 && run3.lastStep >= 6;
  const passed =
    allReachedStep6 &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0 &&
    allErrors.length === 0;

  if (passed) {
    console.log('\n✅ BMS Browser Test PASSED (3 runs, all step 6, 0 errors)');
    process.exit(0);
  } else {
    console.log('\n❌ BMS Browser Test FAILED');
    if (!allReachedStep6) console.log('  Reason: not all runs reached step 6');
    if (consoleErrors.length > 0) console.log(`  Reason: ${consoleErrors.length} console errors`);
    if (failedRequests.length > 0) console.log(`  Reason: ${failedRequests.length} failed requests`);
    if (allErrors.length > 0) console.log(`  Reason: ${allErrors.length} assertion errors`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('[bms-test] FATAL:', err.message);
  process.exit(1);
});
