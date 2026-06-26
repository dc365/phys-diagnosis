const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildColorRampExpression,
  colorRampDomainForLayer,
  buildLayerContourUrl,
  buildLayerGridUrl,
  buildNafpFeaturesUrl,
  buildNafpAreaRiskUrl,
  buildNafpLayerContourUrl,
  buildNafpLayerGridUrl,
  buildNafpLayerMetadataUrl,
  areaRiskPayloadToFeatureCollection,
  areaRiskValidTime,
  featureGeometryBounds,
  featureIndexRows,
  recommendedFeatureLayer,
  legendEndpointLabel,
  primaryFeatureCollection,
  smoothFeatureCollectionForDisplay,
  featureQuality,
  featureDisplayLabel,
  forecastHourLabel,
  pickDefaultRunTime,
  nextForecastHour,
  boundsToImageCoordinates,
  mergeFeatureCollections,
  rankFeatureEvidence,
  runTimesWithDefaultRunTime,
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
    buildLayerGridUrl('risk_short_duration_heavy_rain_score', 'ecmwf demo', 24, 12345),
    '/api/layers/risk_short_duration_heavy_rain_score/grid?run_id=ecmwf%20demo&forecast_hour=24&_=12345',
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
    buildNafpLayerMetadataUrl('z500', 'NAFP_ECTHIN_NC', '2026-06-17T20:00:00', 24, 12345),
    '/api/v1/diagnosis/nafp/layers/z500/metadata?data_code=NAFP_ECTHIN_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&_=12345',
  );
  assert.equal(
    buildNafpLayerGridUrl('risk_short_duration_heavy_rain_score', 'NAFP_ECTHIN_NC', '2026-06-17T20:00:00', 24, 12345),
    '/api/v1/diagnosis/nafp/layers/risk_short_duration_heavy_rain_score/grid?data_code=NAFP_ECTHIN_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&_=12345',
  );
  assert.equal(
    buildNafpLayerContourUrl('mslp', 'NAFP_ECTHIN_NC', '2026-06-17T20:00:00', 24, 12345),
    '/api/v1/diagnosis/nafp/layers/mslp/contours?data_code=NAFP_ECTHIN_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&_=12345',
  );
});

test('NAFP features URL builder sends selected system types in one request', () => {
  assert.equal(
    buildNafpFeaturesUrl(
      ['low_pressure_convergence', 'high_pressure_divergence'],
      'NAFP_ECTHIN_NC',
      '2026-06-17T20:00:00',
      24,
      12345,
    ),
    '/api/v1/diagnosis/nafp/features?data_code=NAFP_ECTHIN_NC&run_time=2026-06-17T20%3A00%3A00&forecast_hour=24&types=low_pressure_convergence%2Chigh_pressure_divergence&_=12345',
  );
});

test('NAFP area risk URL builder follows map scope and selected valid time', () => {
  assert.equal(
    buildNafpAreaRiskUrl({
      dataCode: 'NAFP_ECTHIN_NC',
      runTime: '2026-06-17T20:00:00',
      scopeValue: 'city:350200',
      validTime: '2026-06-18T20:00:00',
      riskType: 'hail',
      cacheBust: 12345,
    }),
    '/api/v1/diagnosis/nafp/area-risks?data_code=NAFP_ECTHIN_NC&run_time=2026-06-17T20%3A00%3A00&region_code=350200&region_level=city&start_time=2026-06-18T20%3A00%3A00&end_time=2026-06-18T20%3A00%3A00&risk_type=hail&_=12345',
  );
  assert.equal(
    buildNafpAreaRiskUrl({
      dataCode: 'NAFP_ECTHIN_NC',
      runTime: '2026-06-17T20:00:00',
      scopeValue: 'town:350203005',
      validTime: '2026-06-18T20:00:00',
      riskType: '',
      cacheBust: 12345,
    }),
    '/api/v1/diagnosis/nafp/area-risks?data_code=NAFP_ECTHIN_NC&run_time=2026-06-17T20%3A00%3A00&town_code=350203005&start_time=2026-06-18T20%3A00%3A00&end_time=2026-06-18T20%3A00%3A00&_=12345',
  );
});

test('areaRiskValidTime derives map valid time from run time and forecast hour', () => {
  assert.equal(areaRiskValidTime('2026-06-17T20:00:00', 24), '2026-06-18T20:00:00');
  assert.equal(areaRiskValidTime('2026-06-17 20', 3), '2026-06-17T23:00:00');
  assert.equal(areaRiskValidTime('', 24), '');
});

test('map run time defaults to current-day 08 while keeping local test runs selectable', () => {
  const runs = [
    { run_time: '2026-06-17T20:00:00', forecast_hours: [0, 24] },
    { run_time: '2026-06-23T08:00:00', forecast_hours: [0, 3, 6] },
  ];

  assert.equal(
    pickDefaultRunTime({
      runTimes: runs,
      backendDefaultRunTime: '2026-06-17T20:00:00',
      now: new Date(2026, 5, 23, 13, 30, 0),
    }),
    '2026-06-23T08:00:00',
  );

  assert.equal(runs[0].run_time, '2026-06-17T20:00:00');
});

test('map run time still defaults to current-day 08 when only local test runs are available', () => {
  assert.equal(
    pickDefaultRunTime({
      runTimes: [{ run_time: '2026-06-17T20:00:00', forecast_hours: [0, 24] }],
      backendDefaultRunTime: '2026-06-17T20:00:00',
      now: new Date(2026, 5, 23, 13, 30, 0),
    }),
    '2026-06-23T08:00:00',
  );
});

test('map run time options add current-day 08 without dropping local test runs', () => {
  const options = runTimesWithDefaultRunTime(
    [{ run_time: '2026-06-17T20:00:00', forecast_hours: [0, 24] }],
    '2026-06-23T08:00:00',
  );

  assert.deepEqual(options.map((run) => run.run_time), [
    '2026-06-23T08:00:00',
    '2026-06-17T20:00:00',
  ]);
  assert.deepEqual(options[0].forecast_hours, [0, 24]);
  assert.equal(options[0].synthetic, true);
  assert.equal(options[1].synthetic, undefined);
});

test('map run time options keep local test runs even when backend inventory is empty', () => {
  const fallbackRuns = [
    { run_time: '2026-06-17T20:00:00', forecast_hours: [0, 24] },
    { run_time: '2026-06-17T08:00:00', forecast_hours: [0, 24] },
  ];
  const defaultRunTime = pickDefaultRunTime({
    runTimes: [],
    now: new Date(2026, 5, 23, 13, 30, 0),
  });
  const options = runTimesWithDefaultRunTime([], defaultRunTime, { fallbackRunTimes: fallbackRuns });

  assert.deepEqual(options.map((run) => run.run_time), [
    '2026-06-23T08:00:00',
    '2026-06-17T20:00:00',
    '2026-06-17T08:00:00',
  ]);
  assert.equal(options[0].synthetic, true);
  assert.equal(options[1].synthetic, undefined);
  assert.equal(options[2].synthetic, undefined);
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

test('risk score layers use a fixed 0-1 color ramp domain', () => {
  assert.deepEqual(
    colorRampDomainForLayer('risk_short_duration_heavy_rain_score', { min: 0.02, max: 0.92 }),
    { min: 0, max: 1 },
  );
  assert.deepEqual(
    colorRampDomainForLayer('risk_thunderstorm_gale_score', { min: 0.03, max: 0.55 }),
    { min: 0, max: 1 },
  );
  assert.deepEqual(
    colorRampDomainForLayer('cape', { min: 120, max: 2600 }),
    { min: 120, max: 2600 },
  );
});

test('risk score legend endpoints show the score values without repeating the 0-1 range', () => {
  assert.equal(legendEndpointLabel(0, '0-1', '低值'), '0');
  assert.equal(legendEndpointLabel(1, '0-1', '高值'), '1');
  assert.equal(legendEndpointLabel(0, 'risk_score', '低值'), '0');
  assert.equal(legendEndpointLabel(1002, 'hPa', '低值'), '低值 1002 hPa');
  assert.equal(legendEndpointLabel(12.345, 'm/s', '高值'), '高值 12.35 m/s');
});

test('areaRiskPayloadToFeatureCollection maps dominant town risk to centroid points', () => {
  const fc = areaRiskPayloadToFeatureCollection({
    risk_metadata: {
      hail: { hazard_type: 'hail', label: '冰雹', source_grid: 'risk_hail_score' },
      short_duration_heavy_rain: {
        hazard_type: 'short_duration_heavy_rain',
        label: '短时强降水',
        source_grid: 'risk_short_duration_heavy_rain_score',
      },
    },
    items: [
      {
        area: {
          town_code: '350203005',
          town_name: '滨海街道',
          county_name: '思明区',
          city_name: '厦门市',
          station_count: 7,
          bbox: [118.05, 24.4, 118.15, 24.5],
        },
        forecast_hour: 24,
        valid_time: '2026-06-18T20:00:00',
        risks: [
          {
            hazard_type: 'hail',
            label: '冰雹',
            score: 0.35,
            risk_level: 'low',
            source_grid: 'risk_hail_score',
            feature_type: 'hail_risk',
            evidence_chain: { dominant_factors: [], source_paths: ['/hail.nc'] },
          },
          {
            hazard_type: 'short_duration_heavy_rain',
            label: '短时强降水',
            score: 0.72,
            risk_level: 'high',
            source_grid: 'risk_short_duration_heavy_rain_score',
            feature_type: 'short_duration_heavy_rain_risk',
            evidence_chain: { dominant_factors: [{ label: '低层水汽' }], source_paths: ['/rain.nc'] },
          },
        ],
      },
    ],
  }, { mode: 'dominant' });

  assert.equal(fc.type, 'FeatureCollection');
  assert.equal(fc.features.length, 1);
  assert.deepEqual(fc.features[0].geometry.coordinates, [118.1, 24.45]);
  assert.equal(fc.features[0].properties.hazard_type, 'short_duration_heavy_rain');
  assert.equal(fc.features[0].properties.label, '短时强降水');
  assert.equal(fc.features[0].properties.score, 0.72);
  assert.equal(fc.features[0].properties.score_text, '0.720');
  assert.equal(fc.features[0].properties.source_grid, 'risk_short_duration_heavy_rain_score');
  assert.deepEqual(fc.features[0].properties.bbox, [118.05, 24.4, 118.15, 24.5]);
  assert.equal(fc.properties.display_mode, 'dominant');
});

test('areaRiskPayloadToFeatureCollection can show a single selected risk type', () => {
  const fc = areaRiskPayloadToFeatureCollection({
    items: [
      {
        area: { town_code: '350203005', town_name: '滨海街道', bbox: [118, 24, 118.2, 24.2] },
        forecast_hour: 24,
        valid_time: '2026-06-18T20:00:00',
        risks: [
          { hazard_type: 'hail', label: '冰雹', score: 0.35, risk_level: 'low' },
          { hazard_type: 'short_duration_heavy_rain', label: '短时强降水', score: 0.72, risk_level: 'high' },
        ],
      },
    ],
  }, { mode: 'single', riskType: 'hail' });

  assert.equal(fc.features.length, 1);
  assert.equal(fc.features[0].properties.hazard_type, 'hail');
  assert.equal(fc.features[0].properties.score, 0.35);
  assert.equal(fc.properties.display_mode, 'single');
  assert.equal(fc.properties.risk_type, 'hail');
});

test('featureDisplayLabel uses Chinese GIS labels for pressure centers', () => {
  assert.equal(featureDisplayLabel({ feature_type: 'high', label: 'H' }), '高');
  assert.equal(featureDisplayLabel({ feature_type: 'low', label: 'L' }), '低');
});

test('featureDisplayLabel uses classified front labels for front axes', () => {
  assert.equal(
    featureDisplayLabel({
      feature_type: 'front_candidate',
      front_type: 'cold_front',
      front_type_label: '冷锋候选',
      label: '锋面候选',
    }),
    '冷锋候选',
  );
  assert.equal(
    featureDisplayLabel({ feature_type: 'front_candidate', front_type: 'warm_front' }),
    '暖锋候选',
  );
});

test('featureDisplayLabel names extended weather system types directly', () => {
  assert.equal(featureDisplayLabel({ feature_type: 'shear_line' }), '切变线');
  assert.equal(featureDisplayLabel({ feature_type: 'upper_jet' }), '高空急流');
  assert.equal(featureDisplayLabel({ feature_type: 'low_level_convergence_axis' }), '低层辐合轴');
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
    'risk_short_duration_heavy_rain_score',
    'risk_hail_score',
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
    recommendedFeatureLayer({ feature_type: 'upper_jet' }, ['wind300_speed']),
    { layerId: 'wind300_speed', reason: 'upper-jet' },
  );
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'shear_line' }, ['wind850_speed']),
    { layerId: 'wind850_speed', reason: 'wind-shear-line' },
  );
  assert.equal(recommendedFeatureLayer({ feature_type: 'heavy_rain_risk' }, ['heavy_rain_score']), null);
  assert.equal(recommendedFeatureLayer({ feature_type: 'convection_risk' }, ['convection_score']), null);
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

test('primaryFeatureCollection keeps only primary weather systems when metadata is present', () => {
  const fc = {
    type: 'FeatureCollection',
    properties: { summary: 'sample' },
    features: [
      { type: 'Feature', properties: { id: 'main', primary: true, display_rank: 1 } },
      { type: 'Feature', properties: { id: 'support', primary: false, display_rank: 2 } },
      { type: 'Feature', properties: { id: 'legacy' } },
    ],
  };

  assert.deepEqual(primaryFeatureCollection(fc), {
    type: 'FeatureCollection',
    properties: {
      summary: 'sample',
      total_features: 3,
      displayed_features: 1,
      display_filter: 'primary',
    },
    features: [
      { type: 'Feature', properties: { id: 'main', primary: true, display_rank: 1 } },
    ],
  });
  assert.deepEqual(
    primaryFeatureCollection({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: { id: 'legacy' } }],
    }).features,
    [{ type: 'Feature', properties: { id: 'legacy' } }],
  );
});

test('smoothFeatureCollectionForDisplay smooths display line geometry without mutating source', () => {
  const fc = {
    type: 'FeatureCollection',
    properties: { summary: 'sample' },
    features: [
      {
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: [[100, 20], [101, 21], [102, 20]] },
        properties: { id: 'trough-1', feature_type: 'trough' },
      },
    ],
  };

  const smoothed = smoothFeatureCollectionForDisplay(fc);

  assert.notEqual(smoothed, fc);
  assert.deepEqual(fc.features[0].geometry.coordinates, [[100, 20], [101, 21], [102, 20]]);
  assert.deepEqual(smoothed.properties, {
    summary: 'sample',
    geometry_smoothing: 'display-chaikin',
  });
  assert.equal(smoothed.features[0].properties.id, 'trough-1');
  assert.equal(smoothed.features[0].geometry.type, 'LineString');
  assert.deepEqual(smoothed.features[0].geometry.coordinates[0], [100, 20]);
  assert.deepEqual(smoothed.features[0].geometry.coordinates.at(-1), [102, 20]);
  assert.ok(smoothed.features[0].geometry.coordinates.length > fc.features[0].geometry.coordinates.length);
});

test('smoothFeatureCollectionForDisplay keeps polygon rings closed for display outlines', () => {
  const fc = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [100, 20],
            [101, 20],
            [101, 21],
            [100, 21],
            [100, 20],
          ]],
        },
        properties: { id: 'subtropical-high-1', feature_type: 'subtropical_high' },
      },
    ],
  };

  const smoothed = smoothFeatureCollectionForDisplay(fc, { iterations: 2 });
  const ring = smoothed.features[0].geometry.coordinates[0];

  assert.equal(smoothed.features[0].geometry.type, 'Polygon');
  assert.deepEqual(ring[0], ring.at(-1));
  assert.ok(ring.length > fc.features[0].geometry.coordinates[0].length);
});
