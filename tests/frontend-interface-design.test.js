const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const css = fs.readFileSync('frontend/styles.css', 'utf8');
const html = fs.readFileSync('frontend/index.html', 'utf8');
const app = fs.readFileSync('frontend/app.js', 'utf8');

test('interface design system is saved for future sessions', () => {
  const system = fs.readFileSync('.interface-design/system.md', 'utf8');
  const design = fs.readFileSync('DESIGN.md', 'utf8');

  assert.match(system, /气象值班台/);
  assert.match(system, /证据链检查器/);
  assert.match(system, /边框为主/);
  assert.match(system, /4px/);
  assert.match(design, /天气形势分析与物理量诊断工作台设计约定/);
  assert.match(design, /Visual Theme and Atmosphere/);
  assert.match(design, /工作台路径/);
  assert.match(design, /证据链/);
});

test('css tokens use meteorological domain language', () => {
  for (const token of [
    '--sky-canvas',
    '--cloud-panel',
    '--isobar-line',
    '--radar-cyan',
    '--warning-red',
    '--analysis-rail',
  ]) {
    assert.match(css, new RegExp(token));
  }
  assert.match(css, /oklch\(/);
  assert.match(css, /--text:\s*var\(--ink\)/);
});

test('admin shell has a duty workflow signature instead of a generic sidebar', () => {
  assert.match(html, /class="sidebar-context"/);
  assert.match(html, /值班闭环/);
  assert.match(html, /class="workspace-ribbon"/);
  assert.match(html, /data-ribbon-step="diagnosis-workbench"/);
  assert.match(html, /data-ribbon-step="algorithm-governance"/);
  assert.match(html, /class="nav-section-label">研判/);
  assert.match(html, /class="nav-section-label">治理/);
  assert.match(html, /aria-current="page"/);
  assert.match(css, /\.sidebar-flow::before/);
  assert.match(css, /\.workspace-ribbon\[data-active-view="diagnosis-workbench"\]/);
  assert.match(app, /setAttribute\('aria-current', 'page'\)/);
  assert.match(app, /setAttribute\('data-active-view', view\)/);
});

test('status strip carries duty-specific metric roles', () => {
  assert.match(html, /class="metric-cell primary-metric"/);
  assert.match(html, /class="metric-cell risk-cell risk-metric"/);
  assert.match(html, /class="status-message briefing-strip"/);
});

test('status updates preserve the briefing strip role', () => {
  assert.match(app, /status-message briefing-strip/);
});

test('evidence chain has a visible trace signature', () => {
  assert.match(css, /\.chain-row::before/);
  assert.match(css, /\.evidence-list::before/);
  assert.match(css, /\.evidence-item::before/);
  assert.match(css, /\.evidence-item::before[\s\S]*background: var\(--radar-cyan\)/);
});

test('weather systems render as grouped object stacks instead of one long table', () => {
  assert.match(html, /id="systemsGroupList"/);
  assert.match(app, /groupSystemsForDuty/);
  assert.match(app, /data-group-toggle/);
  assert.match(css, /\.system-group/);
  assert.match(css, /\.system-object-row/);
});

test('overview page uses a traceable duty briefing layout', () => {
  assert.match(html, /class="overview-layout"/);
  assert.match(html, /class="overview-flow"/);
  assert.match(html, /class="reasoning-rail"/);
  assert.doesNotMatch(html, /class="[^"]*demo-script[^"]*"/);
  assert.doesNotMatch(html, /演示路径/);
  assert.match(css, /\.overview-flow/);
  assert.match(css, /\.flow-step::before/);
  assert.match(css, /\.reasoning-step::before/);
});

test('rule explanation cards wrap long identifiers without clipping text', () => {
  assert.match(css, /\.rule-explanation-panel\s*{[\s\S]*minmax\(min\(100%, 360px\), 1fr\)/);
  assert.match(css, /\.rule-explanation-card\s*{[\s\S]*container-type:\s*inline-size/);
  assert.match(css, /\.rule-explanation-card\s*{[\s\S]*overflow:\s*hidden/);
  assert.match(css, /\.rule-explanation-card header > div\s*{[\s\S]*min-width:\s*0/);
  assert.match(css, /\.rule-explanation-card \.type-pill\s*{[\s\S]*white-space:\s*normal/);
  assert.match(css, /\.rule-mini-grid li\s*{[\s\S]*overflow-wrap:\s*anywhere/);
  assert.match(css, /\.rule-threshold-chip strong,\s*\.rule-threshold-chip em\s*{[\s\S]*white-space:\s*normal/);
  assert.match(css, /@container \(max-width:\s*430px\)\s*{[\s\S]*\.rule-mini-grid\s*{[\s\S]*grid-template-columns:\s*1fr/);
});

test('admin redesign avoids broad left-border accents and supports reduced motion', () => {
  assert.doesNotMatch(css, /border-left:\s*[2-9]px/);
  assert.match(css, /prefers-reduced-motion/);
  assert.doesNotMatch(css, /transition:\s*all/);
});
