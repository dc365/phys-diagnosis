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
  assert.match(adminExtension, /#service-status \.service-grid/);
  assert.match(adminExtension, /\/api\/v1\/diagnosis\/nafp\/precompute\/status/);
  assert.match(adminExtension, /\/api\/v1\/diagnosis\/nafp\/precompute\/run/);
  assert.match(adminExtension, /precomputeForce/);
  assert.match(adminExtension, /precomputeHours/);
  assert.equal(fs.existsSync('frontend/precompute.html'), false);
});
