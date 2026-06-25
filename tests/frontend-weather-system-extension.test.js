const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('frontend/map.html', 'utf8');
const extension = fs.readFileSync('frontend/weather-system-frontend-extension.js', 'utf8');

const newTypes = [
  'shear_line',
  'front_with_shear',
  'low_level_convergence_axis',
  'upper_divergence_axis',
  'cold_vortex',
  'mid_level_vortex',
  'upper_jet',
  'upper_jet_exit_region',
  'pv_anomaly',
  'surface_front_candidate',
  'dryline_candidate',
];

test('map page loads weather-system extension before main map script', () => {
  const extensionIndex = html.indexOf('/static/weather-system-frontend-extension.js');
  const mapIndex = html.indexOf('/static/map.js');
  assert.ok(extensionIndex > 0, 'extension script is missing');
  assert.ok(mapIndex > extensionIndex, 'extension must load before map.js');
});

test('weather-system extension registers all integrated feature types', () => {
  newTypes.forEach((type) => assert.match(extension, new RegExp(`type: '${type}'`)));
  assert.match(extension, /patchWeatherTypeIteration/);
  assert.match(extension, /patchFeatureTypeNames/);
  assert.match(extension, /patchFeatureColorEntries/);
});

test('weather-system extension wires display labels, layer recommendations and colors', () => {
  assert.match(extension, /featureDisplayLabel/);
  assert.match(extension, /recommendedFeatureLayer/);
  assert.match(extension, /featureColorMatchExpression/);
  assert.match(extension, /weather-features/);
  assert.match(extension, /styleExtendedToggle/);
  assert.match(extension, /feature-swatch-line/);
  assert.match(extension, /feature-swatch-point/);
  assert.match(extension, /feature-swatch-area/);
});
