const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const mapHtml = fs.readFileSync('frontend/map.html', 'utf8');
const mapExtension = fs.readFileSync('frontend/precompute-map-extension.js', 'utf8');
const adminExtension = fs.readFileSync('frontend/precompute-admin-extension.js', 'utf8');
const mainPy = fs.readFileSync('backend/app/main.py', 'utf8');

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

test('precompute monitor is integrated into the admin shell, not a standalone page', () => {
  assert.match(mainPy, /precompute-admin-extension\.js/);
  assert.match(adminExtension, /nafpPrecomputePanel/);
  assert.match(adminExtension, /#automaticDiagnosisPanels/);
  assert.doesNotMatch(adminExtension, /#service-status \.service-grid/);
  assert.match(adminExtension, /auto-remedy-panel/);
  assert.match(adminExtension, /const API_BASE = '\/api\/v1\/diagnosis\/nafp\/precompute'/);
  assert.match(adminExtension, /\$\{API_BASE\}\/status/);
  assert.match(adminExtension, /\$\{API_BASE\}\/run/);
  assert.match(adminExtension, /precomputeForce/);
  assert.match(adminExtension, /precomputeHours/);
  assert.equal(fs.existsSync('frontend/precompute.html'), false);
});

test('diagnosis workbench exposes editable automatic preprocessing schedule', () => {
  assert.match(mainPy, /start_auto_diagnosis_scheduler/);
  assert.match(adminExtension, /AUTO_SCHEDULE_API/);
  assert.match(adminExtension, /autoSchedulePanel/);
  assert.match(adminExtension, /autoScheduleForm/);
  assert.match(adminExtension, /autoScheduleMode/);
  assert.match(adminExtension, /autoScheduleInterval/);
  assert.match(adminExtension, /autoScheduleFixedTimes/);
  assert.match(adminExtension, /默认每 1 小时/);
  assert.match(adminExtension, /\/api\/v1\/admin\/auto-diagnostics\/schedule/);
});

test('precompute status polling is non-overlapping and backs off while idle or hidden', () => {
  assert.match(adminExtension, /statusRefreshPromise/);
  assert.match(adminExtension, /document\.hidden/);
  assert.match(adminExtension, /payload\?\.status === 'running'/);
  assert.doesNotMatch(adminExtension, /setInterval\(\(\) => refreshStatus/);
});
