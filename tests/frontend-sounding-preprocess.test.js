const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const mainPy = fs.readFileSync('backend/app/main.py', 'utf8');
const extension = fs.readFileSync('frontend/sounding-preprocess-admin-extension.js', 'utf8');
const backendApi = fs.readFileSync('backend/app/api/v1/sounding_preprocess.py', 'utf8');
const preprocessModule = fs.readFileSync('weather_diag/diagnosis/sounding_preprocess.py', 'utf8');

test('admin shell injects sounding preprocessing extension', () => {
  assert.match(mainPy, /sounding_preprocess import router as public_sounding_preprocess_router/);
  assert.match(mainPy, /public_sounding_preprocess_router/);
  assert.match(mainPy, /sounding-preprocess-admin-extension\.js/);
});

test('sounding preprocessing extension integrates into data-fields backend panel', () => {
  assert.match(extension, /soundingPreprocessPanel/);
  assert.match(extension, /#data-fields \.data-grid/);
  assert.match(extension, /探空站资料预处理/);
  assert.match(extension, /\/api\/v1\/sounding\/preprocess\/status/);
  assert.match(extension, /\/api\/v1\/sounding\/preprocess\/run/);
  assert.match(extension, /soundingPreprocessForce/);
});

test('sounding preprocessing API exposes status run report and files endpoints', () => {
  assert.match(backendApi, /@router\.get\("\/status"\)/);
  assert.match(backendApi, /@router\.post\("\/run"\)/);
  assert.match(backendApi, /@router\.get\("\/report"\)/);
  assert.match(backendApi, /@router\.get\("\/files"\)/);
});

test('sounding preprocessing module includes core QC rules and cleaned output', () => {
  assert.match(preprocessModule, /dewpoint_exceeds_temperature/);
  assert.match(preprocessModule, /duplicate_station_level/);
  assert.match(preprocessModule, /z500_buddy_outlier/);
  assert.match(preprocessModule, /standard_level_coverage/);
  assert.match(preprocessModule, /cleaned_csv_path/);
  assert.match(preprocessModule, /qc_flags/);
});
