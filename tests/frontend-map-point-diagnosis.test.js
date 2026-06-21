const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('frontend/map.html', 'utf8');
const css = fs.readFileSync('frontend/map.css', 'utf8');
const mapJs = fs.readFileSync('frontend/map.js', 'utf8');

test('map page exposes a point diagnosis probe mode', () => {
  assert.match(html, /id="btnPointProbe"/);
  assert.match(html, /aria-pressed="false"/);
  assert.match(html, />点位诊断</);
  assert.match(html, /id="pointDataCodeSelect"/);
  assert.match(html, /id="pointRunTimeSelect"/);
  assert.match(html, /id="pointDiagnosisPanel"/);
});

test('point probe posts clicked coordinates to the NAFP point diagnosis API', () => {
  assert.match(mapJs, /function selectedPointDataCode\(\)/);
  assert.match(mapJs, /function selectedPointRunTime\(\)/);
  assert.match(mapJs, /function setPointProbeActive\(active\)/);
  assert.match(mapJs, /function diagnosePointAt\(lngLat\)/);
  assert.match(mapJs, /\/api\/v1\/diagnosis\/nafp\/point/);
  assert.match(mapJs, /data_code: selectedPointDataCode\(\)/);
  assert.match(mapJs, /run_time: selectedPointRunTime\(\)/);
  assert.match(mapJs, /lat: Number\(lngLat\.lat\.toFixed\(6\)\)/);
  assert.match(mapJs, /lon: Number\(lngLat\.lng\.toFixed\(6\)\)/);
  assert.match(mapJs, /aria-pressed/);
});

test('point probe loads data codes and run times from backend configuration', () => {
  assert.match(mapJs, /async function refreshPointDataSources\(\)/);
  assert.match(mapJs, /\/api\/v1\/admin\/data-sources/);
  assert.match(mapJs, /async function refreshPointRunTimes\(\)/);
  assert.match(mapJs, /\/api\/v1\/admin\/data-sources\/\$\{encodeURIComponent\(dataCode\)\}\/nafp-runs/);
  assert.doesNotMatch(mapJs, /const POINT_DIAGNOSIS_RUN_TIME/);
});

test('point diagnosis renders scores and evidence chain trace instead of raw json', () => {
  assert.match(mapJs, /function renderPointDiagnosis\(result\)/);
  assert.match(mapJs, /point-score-grid/);
  assert.match(mapJs, /point-evidence-chain/);
  assert.match(mapJs, /point-evidence-item/);
  assert.match(mapJs, /source_path/);
  assert.match(mapJs, /diagnosis_conclusions/);
});

test('point diagnosis renders multi-hazard risk cards before raw details', () => {
  assert.match(mapJs, /risk_diagnoses/);
  assert.match(mapJs, /point-risk-card/);
  assert.match(mapJs, /pointTargetNames = \{[\s\S]*short_duration_heavy_rain/);
  assert.match(mapJs, /pointTargetNames = \{[\s\S]*hail/);
});

test('point diagnosis groups risks into two operational channels', () => {
  assert.match(mapJs, /const pointRiskChannels = \[/);
  assert.match(mapJs, /label: '强降水风险'[\s\S]*hazards: \['persistent_heavy_rain', 'short_duration_heavy_rain'\]/);
  assert.match(
    mapJs,
    /label: '强对流风险'[\s\S]*hazards: \['short_duration_heavy_rain', 'thunderstorm_gale', 'hail', 'rotating_storm_or_supercell'\]/,
  );
  assert.match(mapJs, /function renderPointRiskChannelSection/);
  assert.match(mapJs, /point-risk-channel/);
  assert.doesNotMatch(mapJs, /hazards: \[[^\]]*severe_convection_composite[^\]]*\]/);
});

test('right panel separates elements risks and weather systems', () => {
  assert.match(html, /class="layer-panel" aria-label="要素、风险与天气系统"/);
  assert.match(html, /<h2>要素<\/h2>[\s\S]*id="layerChips"[\s\S]*<h2>风险<\/h2>/);
  assert.match(html, /<h2>风险<\/h2>[\s\S]*id="riskLayerChips"[\s\S]*id="riskFeatureToggles"[\s\S]*<h2>天气系统<\/h2>/);
  assert.match(mapJs, /const weatherSystemFeatureTypes = \[/);
  assert.match(mapJs, /const riskFeatureTypes = \[/);
  assert.match(mapJs, /function isRiskLayer\(layerId\)/);
  assert.match(mapJs, /renderLayerChipGroup\('layerChips', isElementLayer\)/);
  assert.match(mapJs, /renderLayerChipGroup\('riskLayerChips', isRiskLayer\)/);
  assert.match(mapJs, /#featureToggles input:checked, #riskFeatureToggles input:checked/);
  assert.match(mapJs, /riskFeatureToggles'\)\.addEventListener\('change', handleFeatureToggleChange\)/);
});

test('point probe has a map marker and dense evidence-panel styling', () => {
  assert.match(css, /\.point-probe-toggle\.active/);
  assert.match(css, /\.point-probe-marker/);
  assert.match(css, /\.point-score-grid/);
  assert.match(css, /\.point-risk-channel/);
  assert.match(css, /\.point-evidence-chain/);
  assert.match(css, /\.point-evidence-item::before/);
});
