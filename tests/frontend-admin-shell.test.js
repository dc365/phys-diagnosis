const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const css = fs.readFileSync('frontend/styles.css', 'utf8');
const app = fs.readFileSync('frontend/app.js', 'utf8');

test('desktop admin shell isolates scrolling to the main workspace', () => {
  assert.match(css, /@media\s*\(min-width:\s*761px\)/);
  assert.match(css, /body\s*{[^}]*overflow:\s*hidden/s);
  assert.match(css, /\.admin-shell\s*{[^}]*height:\s*100vh/s);
  assert.match(css, /\.sidebar\s*{[^}]*position:\s*sticky[^}]*top:\s*0[^}]*height:\s*100vh[^}]*overflow:\s*auto/s);
  assert.match(css, /\.main-stage\s*{[^}]*height:\s*100vh[^}]*overflow:\s*auto/s);
  assert.match(css, /\.main-stage\s*{[^}]*overflow-anchor:\s*none/s);
  assert.match(css, /\.main-stage\s*{[^}]*scroll-behavior:\s*auto/s);
});

test('admin shell opens with a system overview before operational work areas', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');

  for (const view of [
    'system-overview',
    'diagnosis-workbench',
    'area-risk-workbench',
    'algorithm-governance',
    'data-fields',
    'service-status',
  ]) {
    assert.match(html, new RegExp(`data-view="${view}"`));
    assert.match(html, new RegExp(`id="${view}"`));
  }

  assert.match(html, /class="nav-item active" href="#system-overview" data-view="system-overview"/);
  assert.match(html, /class="module-panel active" id="system-overview"/);
  assert.match(html, /class="module-panel" id="diagnosis-workbench"[^>]*hidden/);
  assert.match(html, /class="module-panel" id="area-risk-workbench"[^>]*hidden/);
  assert.match(html, /class="module-panel" id="algorithm-governance"/);
  assert.doesNotMatch(html, /diagnosis-replay/);
});

test('overview explains flow, capabilities, and reasoning without demo path', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');

  assert.match(html, /id="overviewFlow"/);
  assert.match(html, /id="overviewCapabilityGrid"/);
  assert.match(html, /id="overviewReasoningRail"/);
  assert.doesNotMatch(html, /id="overviewDemoScript"/);
  assert.match(html, /数值预报格点/);
  assert.match(html, /水汽[\s\S]*抬升[\s\S]*不稳定[\s\S]*风切变/);
  assert.match(html, /证据链/);
  assert.doesNotMatch(html, /演示路径/);
  assert.doesNotMatch(html, /演示讲解顺序/);
});

test('admin navigation switches modules without scrolling the whole page', () => {
  assert.match(app, /function\s+setupNavigation\(\)/);
  assert.match(app, /function\s+selectView\(/);
  assert.match(app, /function\s+viewFromHash\(\)/);
  assert.match(app, /function\s+viewFromLocation\(\)/);
  assert.match(app, /function\s+updateViewUrl\(/);
  assert.match(app, /function\s+resetMainStageScroll\(\)/);
  assert.match(app, /const\s+DEFAULT_VIEW\s*=\s*'system-overview'/);
  assert.match(app, /scrollRestoration\s*=\s*'manual'/);
  assert.match(app, /searchParams\.delete\('view'\)/);
  assert.match(app, /replaceState\(null/);
  assert.match(app, /event\.preventDefault\(\)/);
  assert.match(app, /querySelectorAll\('\.module-panel'\)/);
  assert.match(app, /hidden = panel\.dataset\.viewPanel !== view/);
  assert.match(app, /mainStage\.style\.overflow = 'hidden'/);
  assert.match(app, /mainStage\.scrollTop = 0/);
  assert.match(app, /requestAnimationFrame\(reset\)/);
  assert.doesNotMatch(app, /scrollIntoView\(/);
});

test('diagnosis controls show model labels while submitting configured data codes', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');

  assert.match(html, /<label[^>]*for="dataCodeSelect"/);
  assert.match(html, /id="dataCodeSelect"/);
  assert.match(html, />模式</);
  assert.doesNotMatch(html, /id="rootInput"/);

  assert.match(app, /function\s+loadDataSources\(\)/);
  assert.match(app, /\/api\/v1\/admin\/data-sources/);
  assert.match(app, /\$\('dataCodeSelect'\)\.value/);
  assert.match(app, /function\s+dataSourceLabel/);
  assert.match(app, /<option value="\$\{escapeHtml\(item\.code\)\}">\$\{escapeHtml\(dataSourceLabel\(item\)\)\}<\/option>/);
  assert.match(app, /后台映射/);
  assert.doesNotMatch(app, /item\.code\)} ·/);
  assert.doesNotMatch(app, /selected\.name \|\| selected\.code/);
  assert.doesNotMatch(app, /DEFAULT_NAFP_ROOT/);
});

test('diagnosis workbench supports configured multi-hour batches', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');

  assert.match(html, /id="forecastHourChips"/);
  assert.match(html, /id="forecastSelectionSummary"/);
  assert.match(html, /id="selectAllForecastHours"/);
  assert.match(html, /id="selectDefaultForecastHour"/);
  assert.match(html, /id="batchSummary"/);
  assert.match(app, /DEFAULT_FORECAST_HOURS = Array\.from\(\{ length: 81 \}/);
  assert.match(app, /buildNafpSituationBatchRequest/);
  assert.match(app, /\/api\/v1\/diagnosis\/nafp\/situations/);
  assert.match(app, /function selectedForecastHours/);
  assert.match(app, /function renderForecastHourChips/);
  assert.match(app, /function toggleForecastHour/);
  assert.match(app, /function selectForecastHourRange/);
});

test('admin boot waits for an explicit diagnosis run', () => {
  const bootBody = app.match(/async function bootAdmin\(\) \{([\s\S]*?)\n\}/)?.[1] || '';

  assert.match(bootBody, /await dataSourcesReady/);
  assert.doesNotMatch(bootBody, /runDiagnosis\(\)/);
});

test('admin default times use today 08 and next-day 08 window', () => {
  assert.doesNotMatch(app, /DEFAULT_RUN_TIME/);
  assert.match(app, /\$\('runTimeInput'\)\.value = buildDefaultTimeWindow\(\)\.runTime/);
  assert.match(app, /const defaults = buildDefaultTimeWindow\(\)/);
  assert.match(app, /\$\('areaRiskRunTimeInput'\)\.value = defaults\.runTime/);
  assert.match(app, /\$\('areaRiskStartTimeInput'\)\.value = defaults\.startTime/);
  assert.match(app, /\$\('areaRiskEndTimeInput'\)\.value = defaults\.endTime/);
});

test('diagnosis workbench renders subtropical high batch trend summary', () => {
  assert.match(app, /subtropical_high_trend/);
  assert.match(app, /trend_summary/);
  assert.match(app, /副高演变/);
});

test('diagnosis workbench renders weather situation evolution panel', () => {
  assert.match(app, /situation_evolution/);
  assert.match(app, /renderSituationEvolution/);
  assert.match(app, /天气形势演变/);
  assert.match(app, /低空急流/);
  assert.match(app, /水汽输送/);
});

test('diagnosis workbench renders risk diagnoses instead of MVP risk chains', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');

  assert.match(html, />风险诊断</);
  assert.match(html, /暂无风险诊断/);
  assert.match(html, /选择天气系统或风险诊断/);
  assert.doesNotMatch(html, /风险证据链/);
  assert.doesNotMatch(html, />风险链</);

  assert.match(app, /risk_diagnoses/);
  assert.match(app, /function\s+renderRisks/);
  assert.match(app, /selectItem\('risk'/);
  assert.doesNotMatch(app, /暂无风险链/);
});

test('admin shell exposes area risk as an independent workbench', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');

  assert.match(html, /href="#area-risk-workbench" data-view="area-risk-workbench"/);
  assert.match(html, /<strong>区域风险<\/strong>/);
  assert.match(html, /id="areaRiskForm"/);
  assert.match(html, /id="areaRiskScopeSelect"/);
  assert.match(html, /id="areaRiskTypeSelect"/);
  assert.match(html, /id="areaRiskRows"/);
  assert.match(html, /id="areaRiskInspectorBody"/);
  assert.doesNotMatch(html, /areaRiskAllTimesToggle/);
  assert.doesNotMatch(html, /时段模式|全部时效/);

  assert.match(app, /\/api\/v1\/diagnosis\/nafp\/areas/);
  assert.match(app, /\/api\/v1\/diagnosis\/nafp\/area-risks/);
  assert.match(app, /function\s+loadAreaRiskAreas\(\)/);
  assert.match(app, /function\s+queryAreaRisks\(\)/);
  assert.match(app, /function\s+renderAreaRiskRows/);
  assert.match(app, /function\s+renderAreaRiskInspector/);
  assert.doesNotMatch(app, /syncAreaRiskTimeMode|areaRiskAllTimesToggle|allTimes/);
});

test('admin UI does not render backend data paths', () => {
  assert.doesNotMatch(app, /source_path/);
  assert.doesNotMatch(app, /source_paths/);
  assert.doesNotMatch(css, /source-path/);
});
