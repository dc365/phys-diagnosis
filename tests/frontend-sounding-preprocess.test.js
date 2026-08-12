const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const mainPy = fs.readFileSync('backend/app/main.py', 'utf8');
const extension = fs.readFileSync('frontend/sounding-preprocess-admin-extension.js', 'utf8');
const backendApi = fs.readFileSync('backend/app/api/v1/sounding_preprocess.py', 'utf8');
const preprocessModule = fs.readFileSync('weather_diag/diagnosis/sounding_preprocess.py', 'utf8');
const schedulerModule = fs.readFileSync('weather_diag/diagnosis/auto_scheduler.py', 'utf8');

test('admin shell injects sounding preprocessing extension', () => {
  assert.match(mainPy, /sounding_preprocess import router as public_sounding_preprocess_router/);
  assert.match(mainPy, /public_sounding_preprocess_router/);
  assert.match(mainPy, /sounding-preprocess-admin-extension\.js/);
});

test('sounding preprocessing extension integrates into diagnosis workbench', () => {
  assert.match(extension, /soundingPreprocessPanel/);
  assert.match(extension, /#automaticDiagnosisPanels/);
  assert.doesNotMatch(extension, /#data-fields \.data-grid/);
  assert.match(extension, /探空站资料预处理/);
  assert.match(extension, /auto-remedy-panel/);
  assert.match(extension, /const API_BASE = '\/api\/v1\/sounding\/preprocess'/);
  assert.match(extension, /\$\{API_BASE\}\/status/);
  assert.match(extension, /\$\{API_BASE\}\/run/);
  assert.match(extension, /soundingPreprocessForce/);
});

test('sounding preprocessing can autostart with backend diagnostics', () => {
  assert.match(mainPy, /start_auto_diagnosis_scheduler/);
  assert.match(mainPy, /start_auto_diagnostics/);
  assert.match(schedulerModule, /autostart_sounding_preprocess/);
  assert.match(preprocessModule, /def autostart_sounding_preprocess/);
  assert.match(preprocessModule, /threading\.Thread/);
  assert.match(preprocessModule, /WEATHER_DIAG_AUTO_SOUNDING_PREPROCESS/);
});

test('sounding preprocessing summary formats update time for people', () => {
  assert.match(extension, /function formatUpdatedAt/);
  assert.match(extension, /toLocaleString\('zh-CN'/);
  assert.match(extension, /formatUpdatedAt\(status\?\.updated_at\)/);
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
