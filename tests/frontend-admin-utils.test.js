const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildNafpSituationRequest,
  summarizeSituation,
  evidenceLevelLabel,
  formatIsoForDuty,
} = require('../frontend/admin-utils');

test('buildNafpSituationRequest normalizes run time and forecast hour', () => {
  assert.deepEqual(
    buildNafpSituationRequest('/data/nafp', '2026-06-17 20', '24'),
    { root: '/data/nafp', run_time: '2026-06-17T20:00:00', forecast_hour: 24 },
  );
});

test('summarizeSituation derives duty metrics from diagnosis payload', () => {
  const summary = summarizeSituation({
    systems: [{ type: 'subtropical_high' }, { type: 'trough_candidate' }],
    evidence_chains: [{ level: 'moderate' }, { level: 'high' }],
    missing_fields: [{ field: 'rain6' }],
  });

  assert.deepEqual(summary, {
    systemCount: 2,
    highRiskCount: 1,
    moderateRiskCount: 1,
    missingCount: 1,
    completeness: 94,
  });
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
