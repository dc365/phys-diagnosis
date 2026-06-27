const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const mapHtml = fs.readFileSync('frontend/map.html', 'utf8');
const mapExtension = fs.readFileSync('frontend/precompute-map-extension.js', 'utf8');
const dashboard = fs.readFileSync('frontend/precompute.html', 'utf8');

test('map loads precompute extension before map.js', () => {
  const extensionIndex = mapHtml.indexOf('/static/precompute-map-extension.js');
  const mapIndex = mapHtml.indexOf('/static/map.js');
  assert.ok(extensionIndex > 0, 'precompute map extension is missing');
  assert.ok(mapIndex > extensionIndex, 'precompute extension must load before map.js destructures WeatherMapUtils');
});

test('map feature url points at precomputed NAFP feature endpoint', () => {
  assert.match(mapExtension, /buildNafpFeaturesUrl/);
  assert.match(mapExtension, /\/api\/v1\/diagnosis\/nafp\/precompute\/features/);
  assert.doesNotMatch(mapExtension, /\/api\/v1\/diagnosis\/nafp\/features\?/);
});

test('standalone precompute dashboard exposes status and manual recompute', () => {
  assert.match(dashboard, /NAFP 数值预报诊断任务监控/);
  assert.match(dashboard, /\/api\/v1\/diagnosis\/nafp\/precompute\/status/);
  assert.match(dashboard, /\/api\/v1\/diagnosis\/nafp\/precompute\/run/);
  assert.match(dashboard, /forceSelect/);
  assert.match(dashboard, /forecastHoursInput/);
});
