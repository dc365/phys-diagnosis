const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildColorRampExpression,
  buildLayerGridUrl,
  featureDisplayLabel,
  forecastHourLabel,
  nextForecastHour,
  boundsToImageCoordinates,
  mergeFeatureCollections,
} = require('../frontend/maplibre-utils');

test('boundsToImageCoordinates returns MapLibre image corners clockwise from northwest', () => {
  assert.deepEqual(boundsToImageCoordinates([70, 15, 140, 55]), [
    [70, 55],
    [140, 55],
    [140, 15],
    [70, 15],
  ]);
});

test('buildLayerGridUrl preserves run and forecast query parameters', () => {
  assert.equal(
    buildLayerGridUrl('heavy_rain_score', 'ecmwf demo', 24, 12345),
    '/api/layers/heavy_rain_score/grid?run_id=ecmwf%20demo&forecast_hour=24&_=12345',
  );
});

test('buildColorRampExpression creates a MapLibre interpolate expression', () => {
  assert.deepEqual(buildColorRampExpression(0, 10, ['#fff7ec', '#7f0000']), [
    'interpolate',
    ['linear'],
    ['get', 'value'],
    0,
    '#fff7ec',
    10,
    '#7f0000',
  ]);
});

test('featureDisplayLabel uses Chinese GIS labels for pressure centers', () => {
  assert.equal(featureDisplayLabel({ feature_type: 'high', label: 'H' }), '高');
  assert.equal(featureDisplayLabel({ feature_type: 'low', label: 'L' }), '低');
});

test('forecastHourLabel formats timeline hours in Chinese', () => {
  assert.equal(forecastHourLabel(0), '起报');
  assert.equal(forecastHourLabel(24), '+24小时');
});

test('nextForecastHour moves through available forecast hours', () => {
  assert.equal(nextForecastHour([0, 6, 12], 6, 1), 12);
  assert.equal(nextForecastHour([0, 6, 12], 12, 1), 12);
  assert.equal(nextForecastHour([0, 6, 12], 0, -1), 0);
});

test('mergeFeatureCollections flattens successful feature responses', () => {
  const merged = mergeFeatureCollections([
    { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { id: 'a' } }] },
    { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { id: 'b' } }] },
    null,
  ]);

  assert.deepEqual(merged, {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', properties: { id: 'a' } },
      { type: 'Feature', properties: { id: 'b' } },
    ],
  });
});
