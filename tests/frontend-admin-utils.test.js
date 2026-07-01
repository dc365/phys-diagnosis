const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildNafpSituationBatchRequest,
  buildNafpSituationRequest,
  buildAreaRiskQuery,
  buildSoundingAreaRiskQuery,
  buildDefaultTimeWindow,
  flattenAreaRiskRows,
  groupSystemsForDuty,
  summarizeSituation,
  summarizeAreaRiskPayload,
  evidenceLevelLabel,
  formatIsoForDuty,
  chainTypeLabel,
  riskTypeLabel,
  systemTypeLabel,
} = require('../frontend/admin-utils');

test('buildDefaultTimeWindow uses current day 08:00 and next day 08:00', () => {
  assert.deepEqual(
    buildDefaultTimeWindow(new Date(2026, 5, 23, 15, 30)),
    {
      runTime: '2026-06-23T08:00',
      startTime: '2026-06-23T08:00',
      endTime: '2026-06-24T08:00',
    },
  );
});

test('buildNafpSituationRequest normalizes run time and forecast hour', () => {
  assert.deepEqual(
    buildNafpSituationRequest('NAFP_ECTHIN_NC', '2026-06-17 20', '24'),
    { data_code: 'NAFP_ECTHIN_NC', run_time: '2026-06-17T20:00:00', forecast_hour: 24 },
  );
});

test('buildNafpSituationBatchRequest normalizes multi-hour requests', () => {
  assert.deepEqual(
    buildNafpSituationBatchRequest('NAFP_ECTHIN_NC', '2026-06-17 20', ['24', '24', '0']),
    { data_code: 'NAFP_ECTHIN_NC', run_time: '2026-06-17T20:00:00', forecast_hours: [24, 0] },
  );
});

test('summarizeSituation derives duty metrics from primary diagnosis payload', () => {
  const summary = summarizeSituation({
    systems: [
      { type: 'subtropical_high' },
      { type: 'low_pressure_convergence' },
      { type: 'high_pressure_divergence' },
      { type: 'trough_candidate' },
    ],
    risk_diagnoses: [{ risk_level: 'high' }, { level: 'moderate' }, { risk_level: 'medium' }],
    evidence_chains: [{ level: 'high' }],
    missing_fields: [{ field: 'rain6' }],
  });

  assert.deepEqual(summary, {
    systemCount: 2,
    highRiskCount: 1,
    moderateRiskCount: 2,
    missingCount: 1,
    completeness: 94,
  });
});

test('groupSystemsForDuty groups long weather-system lists by type', () => {
  const systems = [
    { id: 'aux-1', type: 'low_pressure_convergence', confidence: 0.9, level: '500/850' },
    { id: 'front-1', type: 'front_candidate', confidence: 0.5, level: '850' },
    { id: 'high-1', type: 'subtropical_high', confidence: 0.8, level: '500' },
    { id: 'front-2', type: 'front_candidate', confidence: 0.7, level: '850' },
    { id: 'front-3', type: 'front_candidate', confidence: 0.6, level: '850' },
  ];

  const groups = groupSystemsForDuty(systems, 2);

  assert.equal(groups.length, 2);
  assert.deepEqual(
    groups.map((group) => group.type),
    ['subtropical_high', 'front_candidate'],
  );
  assert.equal(groups[1].count, 3);
  assert.equal(groups[1].previewItems.length, 2);
  assert.equal(groups[1].remaining, 1);
  assert.equal(groups[1].averageConfidence, 0.6);
  assert.deepEqual(groups[1].levels, ['850']);
});

test('pressure center system labels are operational Chinese labels', () => {
  assert.equal(systemTypeLabel('low_pressure_convergence'), '低压辐合');
  assert.equal(systemTypeLabel('high_pressure_divergence'), '高压辐散');
});

test('moisture and upper-air diagnostics use operational Chinese labels', () => {
  assert.equal(systemTypeLabel('moisture_transport'), '水汽输送');
  assert.equal(systemTypeLabel('moisture_convergence'), '水汽辐合');
  assert.equal(systemTypeLabel('upper_divergence'), '高空辐散');
  assert.equal(chainTypeLabel('dynamic_lift_potential'), '动力抬升潜势');
  assert.equal(chainTypeLabel('precipitation_phase'), '雨雪相态');
});

test('risk diagnoses use six-hazard operational Chinese labels', () => {
  assert.equal(riskTypeLabel('persistent_heavy_rain'), '持续性强降水');
  assert.equal(riskTypeLabel('short_duration_heavy_rain'), '短时强降水');
  assert.equal(riskTypeLabel('thunderstorm_gale'), '雷暴大风/下击暴流');
  assert.equal(riskTypeLabel('hail'), '冰雹');
  assert.equal(riskTypeLabel('rotating_storm_or_supercell'), '旋转风暴/超级单体潜势');
  assert.equal(riskTypeLabel('severe_convection_composite'), '强对流综合风险');
});

test('evidenceLevelLabel returns Chinese operational labels', () => {
  assert.equal(evidenceLevelLabel('high'), '高');
  assert.equal(evidenceLevelLabel('moderate'), '中');
  assert.equal(evidenceLevelLabel('low'), '低');
});

test('formatIsoForDuty keeps invalid or empty values safe', () => {
  assert.equal(formatIsoForDuty('2026-06-18T20:00:00'), '2026-06-18 20:00');
  assert.equal(formatIsoForDuty(''), '-');
});

test('buildAreaRiskQuery encodes town and time-window filters', () => {
  const url = buildAreaRiskQuery({
    dataCode: 'NAFP_ECTHIN_NC',
    runTime: '2026-06-17 20',
    scopeValue: 'town:350203005',
    startTime: '2026-06-18T20:00',
    endTime: '2026-06-18T23:00',
    riskType: 'hail',
  });

  assert.equal(
    url,
    '/api/v1/diagnosis/nafp/area-risks?data_code=NAFP_ECTHIN_NC&run_time=2026-06-17T20%3A00%3A00&town_code=350203005&start_time=2026-06-18T20%3A00%3A00&end_time=2026-06-18T23%3A00%3A00&risk_type=hail',
  );
});

test('buildAreaRiskQuery encodes region and forecast-hour filters', () => {
  const url = buildAreaRiskQuery({
    dataCode: 'NAFP_ECTHIN_NC',
    runTime: '2026-06-17T20:00:00',
    scopeValue: 'city:350200',
    forecastHourStart: 24,
    forecastHourEnd: 48,
    riskType: '',
  });

  assert.match(url, /region_code=350200/);
  assert.match(url, /region_level=city/);
  assert.match(url, /forecast_hour_start=24/);
  assert.match(url, /forecast_hour_end=48/);
  assert.doesNotMatch(url, /risk_type=/);
});

test('buildSoundingAreaRiskQuery encodes sounding csv and area filters', () => {
  const url = buildSoundingAreaRiskQuery({
    csvPath: 'test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625/regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv',
    pressureLevel: 500,
    scopeValue: 'town:350203005',
    riskType: 'short_duration_heavy_rain',
  });

  assert.equal(
    url,
    '/api/v1/sounding/area-risks?csv_path=test_datas%2Fregional_radiosonde_5N55N_50E160E_20260624_20260625%2Fregional_radiosonde_5N55N_50E160E_20260625_20BJT.csv&pressure_level=500&town_code=350203005&risk_type=short_duration_heavy_rain',
  );
});

test('flattenAreaRiskRows turns town-time items into sorted risk rows', () => {
  const rows = flattenAreaRiskRows({
    data_type: 'sounding',
    items: [
      {
        area: { town_code: '350203005', town_name: '滨海街道', county_name: '思明区' },
        forecast_hour: 24,
        valid_time: '2026-06-18T20:00:00',
        risks: [
          { hazard_type: 'hail', label: '冰雹', score: 0.35, level: 'medium', source_grid: 'risk_hail_score' },
          { hazard_type: 'short_duration_heavy_rain', label: '短时强降水', score: 0.72, level: 'high', source_grid: 'risk_short_duration_heavy_rain_score' },
        ],
      },
    ],
  });

  assert.equal(rows.length, 2);
  assert.equal(rows[0].hazard_type, 'short_duration_heavy_rain');
  assert.equal(rows[0].town_name, '滨海街道');
  assert.equal(rows[0].score, 0.72);
  assert.equal(rows[0].data_type, 'sounding');
  assert.equal(rows[0].rowKey, 'sounding|350203005|24|short_duration_heavy_rain');
});

test('summarizeAreaRiskPayload reports highest risk and town count', () => {
  const summary = summarizeAreaRiskPayload({
    summary: { town_count: 3 },
    items: [
      { risks: [{ hazard_type: 'hail', label: '冰雹', score: 0.35, level: 'medium' }] },
      { risks: [{ hazard_type: 'short_duration_heavy_rain', label: '短时强降水', score: 0.72, level: 'high' }] },
    ],
  });

  assert.deepEqual(summary, {
    townCount: 3,
    riskCount: 2,
    highRiskCount: 1,
    maxScore: 0.72,
    leadingRiskLabel: '短时强降水',
  });
});
