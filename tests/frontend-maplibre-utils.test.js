const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildColorRampExpression,
  buildLayerContourUrl,
  buildLayerGridUrl,
  buildNafpFeaturesUrl,
  buildNafpLayerContourUrl,
  buildNafpLayerGridUrl,
  buildNafpLayerMetadataUrl,
  featureGeometryBounds,
  featureIndexRows,
  recommendedFeatureLayer,
  featureQuality,
  featureDisplayLabel,
  forecastHourLabel,
  nextForecastHour,
  boundsToImageCoordinates,
  mergeFeatureCollections,
  rankFeatureEvidence,
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

test('buildLayerContourUrl targets contour GeoJSON for the selected diagnostic layer', () => {
  assert.equal(
    buildLayerContourUrl('mslp', 'ecmwf demo', 24, 12345),
    '/api/layers/mslp/contours?run_id=ecmwf%20demo&forecast_hour=24&_=12345',
  );
});

test('NAFP layer URL builders use data code, run time, forecast hour and cache busting', () => {
  assert.equal(
    buildNafpLayerMetadataUrl('z500', 'NAFP_ECTHIN_NEW_NC', '2026-06-17T20:00:00', 24, 12345),
    '/api/v1/diagnosis/nafp/layers/z500/metadata?data_code=NAFP_ECTHIN_NEW_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&_=12345',
  );
  assert.equal(
    buildNafpLayerGridUrl('heavy_rain_score', 'NAFP_ECTHIN_NEW_NC', '2026-06-17T20:00:00', 24, 12345),
    '/api/v1/diagnosis/nafp/layers/heavy_rain_score/grid?data_code=NAFP_ECTHIN_NEW_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&_=12345',
  );
  assert.equal(
    buildNafpLayerContourUrl('mslp', 'NAFP_ECTHIN_NEW_NC', '2026-06-17T20:00:00', 24, 12345),
    '/api/v1/diagnosis/nafp/layers/mslp/contours?data_code=NAFP_ECTHIN_NEW_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&_=12345',
  );
});

test('NAFP features URL builder sends selected system types in one request', () => {
  assert.equal(
    buildNafpFeaturesUrl(
      ['low_pressure_convergence', 'high_pressure_divergence'],
      'NAFP_ECTHIN_NEW_NC',
      '2026-06-17T20:00:00',
      24,
      12345,
    ),
    '/api/v1/diagnosis/nafp/features?data_code=NAFP_ECTHIN_NEW_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&types=low_pressure_convergence%2Chigh_pressure_divergence&_=12345',
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

test('featureQuality maps confidence into duty-review labels', () => {
  assert.deepEqual(featureQuality({ confidence: 0.81 }), {
    level: 'high',
    label: '高可信',
    scoreText: '0.81',
  });
  assert.deepEqual(featureQuality({ confidence: 0.62 }), {
    level: 'moderate',
    label: '中可信',
    scoreText: '0.62',
  });
  assert.deepEqual(featureQuality({ confidence: 0.41 }), {
    level: 'low',
    label: '低可信',
    scoreText: '0.41',
  });
  assert.deepEqual(featureQuality({}), {
    level: 'pending',
    label: '待核验',
    scoreText: '-',
  });
});

test('rankFeatureEvidence sorts strongest contribution first and keeps source evidence', () => {
  const evidence = [
    { entry_id: 'weak', contribution: 0.1, source_path: '/weak' },
    { entry_id: 'strong', contribution: 0.42, source_path: '/strong' },
    { entry_id: 'weighted', normalized_score: 0.8, weight: 0.4, source_path: '/weighted' },
    { entry_id: 'unscored', source_path: '/unscored' },
  ];

  assert.deepEqual(
    rankFeatureEvidence(evidence).map((item) => item.entry_id),
    ['strong', 'weighted', 'weak', 'unscored'],
  );
});

test('featureGeometryBounds derives bounds from line and polygon geometry', () => {
  assert.deepEqual(
    featureGeometryBounds({
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [100, 20],
          [103, 21],
          [102, 24],
          [100, 20],
        ]],
      },
    }),
    [100, 20, 103, 24],
  );
  assert.deepEqual(
    featureGeometryBounds({
      geometry: {
        type: 'LineString',
        coordinates: [[80, 35], [82, 37], [81, 33]],
      },
    }),
    [80, 33, 82, 37],
  );
});

test('featureIndexRows filters objects and sorts review-first by confidence', () => {
  const features = [
    { properties: { id: 'high-1', feature_type: 'low', confidence: 0.82 } },
    { properties: { id: 'low-1', feature_type: 'low', confidence: 0.42 } },
    { properties: { id: 'mid-1', feature_type: 'high_pressure_divergence', confidence: 0.62 } },
  ];

  assert.deepEqual(
    featureIndexRows(features).map((row) => row.id),
    ['low-1', 'mid-1', 'high-1'],
  );
  assert.deepEqual(
    featureIndexRows(features, { type: 'low' }).map((row) => row.id),
    ['low-1', 'high-1'],
  );
  assert.deepEqual(
    featureIndexRows(features, { quality: 'moderate' }).map((row) => row.id),
    ['mid-1'],
  );
});

test('recommendedFeatureLayer maps weather systems to operational diagnostic layers', () => {
  const available = [
    'z500',
    'mslp',
    'div850',
    'moisture_flux850',
    'heavy_rain_score',
    'convection_score',
  ];

  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'low' }, available),
    { layerId: 'mslp', reason: 'pressure-center' },
  );
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'trough' }, available),
    { layerId: 'z500', reason: '500hpa-height' },
  );
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'low_pressure_convergence' }, available),
    { layerId: 'div850', reason: 'low-level-divergence' },
  );
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'moisture_transport' }, available),
    { layerId: 'moisture_flux850', reason: 'moisture-transport' },
  );
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'heavy_rain_risk' }, available),
    { layerId: 'heavy_rain_score', reason: 'risk-score' },
  );
  assert.equal(recommendedFeatureLayer({ feature_type: 'unknown' }, available), null);
});

test('recommended layer supports multi-hazard risk features', () => {
  const available = [
    'risk_short_duration_heavy_rain_score',
    'risk_thunderstorm_gale_score',
    'risk_hail_score',
  ];
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'short_duration_heavy_rain_risk' }, available),
    { layerId: 'risk_short_duration_heavy_rain_score', reason: 'risk-score' },
  );
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'hail_risk' }, available),
    { layerId: 'risk_hail_score', reason: 'risk-score' },
  );
  assert.equal(
    recommendedFeatureLayer(
      { feature_type: 'short_duration_heavy_rain_risk' },
      ['risk_precipitation_composite_score'],
    ),
    null,
  );
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
