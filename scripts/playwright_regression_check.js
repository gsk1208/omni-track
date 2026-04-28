const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const repoRoot = path.resolve(__dirname, '..');
  const dashboardPath = path.resolve(repoRoot, 'dashboard.html');
  const base = `file://${dashboardPath}`;

  const outDir = process.env.ART_DIR
    ? path.resolve(process.env.ART_DIR)
    : path.resolve(repoRoot, 'artifacts', 'regression');
  fs.mkdirSync(outDir, { recursive: true });

  const outPath = path.join(
    outDir,
    `regression_${new Date().toISOString().replace(/[:.]/g, '-')}.png`
  );

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const blockers = [];

  page.on('pageerror', (e) => blockers.push(`Dashboard JS error: ${e.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') blockers.push(`Console error: ${msg.text()}`);
  });

  await page.goto(base, { waitUntil: 'domcontentloaded' });

  // Wait for API-driven content
  await page.waitForFunction(() => {
    const row = document.getElementById('statRow');
    return row && row.querySelectorAll('.stat-card').length > 0;
  }, { timeout: 30000 });

  // Helper: select metric and assert overlay datasets
  async function checkMetric(metricName, label) {
    await page.click(`.stat-card[data-metric="${metricName}"]`);
    await page.waitForFunction(() => {
      const canvas = document.getElementById('trendChart');
      const chart = (window.Chart && (window.Chart.getChart?.(canvas) || window.Chart.getChart?.('trendChart'))) || null;
      return !!(chart && chart.data && chart.data.datasets);
    }, { timeout: 30000 });

    const hasToggle = await page.$('#toggleForecast');
    if (!hasToggle) {
      blockers.push(`Missing predictive overlay toggle (#toggleForecast) while checking ${label}`);
      return;
    }

    async function waitForOverlayState({ on }) {
      await page.waitForFunction((expectedOn) => {
        const canvas = document.getElementById('trendChart');
        const chart = (window.Chart && (window.Chart.getChart?.(canvas) || window.Chart.getChart?.('trendChart'))) || null;
        const ds = chart?.data?.datasets || [];
        const hasForecast = ds.some(d => d.label === 'Forecast');
        const hasHigh = ds.some(d => d.label === 'Forecast High');
        const hasLow = ds.some(d => d.label === 'Forecast Low');
        const hasBand = hasHigh && hasLow;
        return expectedOn ? (hasForecast && hasBand) : (!hasForecast && !hasHigh && !hasLow);
      }, on, { timeout: 15000 });
    }

    // Force overlay ON
    await page.evaluate(() => {
      const t = document.getElementById('toggleForecast');
      if (!t.checked) { t.checked = true; t.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await waitForOverlayState({ on: true });

    const resOn = await page.evaluate(() => {
      const meta = document.getElementById('forecastMeta')?.textContent || '';
      const canvas = document.getElementById('trendChart');
      const chart = (window.Chart && (window.Chart.getChart?.(canvas) || window.Chart.getChart?.('trendChart'))) || null;
      const ds = chart?.data?.datasets || [];
      const forecast = ds.find(d => d.label === 'Forecast');
      const high = ds.find(d => d.label === 'Forecast High');
      const low = ds.find(d => d.label === 'Forecast Low');
      return {
        meta,
        hasForecast: !!forecast,
        hasBand: !!high && !!low,
        forecastDash: forecast?.borderDash || null,
      };
    });

    // Toggle OFF, verify overlay removed
    await page.evaluate(() => {
      const t = document.getElementById('toggleForecast');
      if (t.checked) { t.checked = false; t.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await waitForOverlayState({ on: false });

    const resOff = await page.evaluate(() => {
      const canvas = document.getElementById('trendChart');
      const chart = (window.Chart && (window.Chart.getChart?.(canvas) || window.Chart.getChart?.('trendChart'))) || null;
      const ds = chart?.data?.datasets || [];
      return {
        hasForecast: ds.some(d => d.label === 'Forecast'),
        hasBand: ds.some(d => d.label === 'Forecast High') || ds.some(d => d.label === 'Forecast Low'),
      };
    });

    // Restore ON for next checks
    await page.evaluate(() => {
      const t = document.getElementById('toggleForecast');
      if (!t.checked) { t.checked = true; t.dispatchEvent(new Event('change', { bubbles: true })); }
    });
    await waitForOverlayState({ on: true });

    if (!resOn.hasForecast) {
      blockers.push(`${label}: forecast line missing when overlay ON (forecastMeta="${resOn.meta}")`);
    } else {
      const dash = Array.isArray(resOn.forecastDash) ? resOn.forecastDash.join(',') : '';
      if (dash !== '6,4') blockers.push(`${label}: forecast line not dashed as expected (borderDash=${JSON.stringify(resOn.forecastDash)})`);
    }
    if (!resOn.hasBand) blockers.push(`${label}: confidence band missing (Forecast High/Low datasets not present)`);
    if (resOff.hasForecast || resOff.hasBand) blockers.push(`${label}: overlay datasets still present when overlay OFF`);
  }

  await checkMetric('body_weight', 'Weight');
  await checkMetric('screen_time_total_min', 'Screen time');
  await checkMetric('cibil_score', 'CIBIL');

  await page.waitForTimeout(500);
  await page.screenshot({ path: outPath, fullPage: true });

  await browser.close();
  console.log(JSON.stringify({ outPath, blockers }, null, 2));
})();

