const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('frontend/index.html', 'utf8');
const app = fs.readFileSync('frontend/app.js', 'utf8');
const css = fs.readFileSync('frontend/styles.css', 'utf8');

test('algorithm management lives under one governance module with tabs', () => {
  assert.match(html, /id="algorithm-governance"/);
  assert.match(html, /data-governance-domain="weather-systems"/);
  assert.match(html, /data-governance-domain="risk-diagnosis"/);
  assert.match(html, /data-governance-tab="algorithms"/);
  assert.match(html, /data-governance-tab="thresholds"/);
  assert.match(html, /data-governance-tab="rule-explanations"/);
  assert.match(html, /data-governance-panel="algorithms"/);
  assert.match(html, /data-governance-panel="thresholds"/);
  assert.match(html, /data-governance-panel="rule-explanations"/);
  assert.doesNotMatch(html, /data-view="weather-system-governance"/);
  assert.doesNotMatch(html, /data-view="risk-diagnosis-governance"/);
});

test('algorithm management panels have stable render targets', () => {
  assert.match(html, /id="algorithmLibrary"/);
  assert.match(html, /id="ruleExplanationPanel"/);
  assert.match(html, /id="governanceDomainSummary"/);
  assert.match(html, /id="algorithmDomainBadge"/);
  assert.match(html, /id="ruleExplanationDomainBadge"/);
  assert.match(html, /id="thresholdMatrixBody"/);
  assert.match(html, /id="thresholdGroupList"/);
  assert.match(html, /id="thresholdGroupTitle"/);
  assert.match(html, /id="saveThresholdMatrix"/);
  assert.doesNotMatch(html, /id="thresholdMatrixOwner"/);
  assert.doesNotMatch(html, />保存人</);
  assert.doesNotMatch(html, /id="runReplayButton"/);
  assert.doesNotMatch(html, /id="replayTableBody"/);
  assert.doesNotMatch(html, /thresholdVersionSelect/);
  assert.doesNotMatch(html, /保存草稿/);
});

test('frontend loads and saves the single default threshold matrix', () => {
  assert.match(app, /\/api\/v1\/admin\/algorithms\/catalog/);
  assert.match(app, /\/api\/v1\/admin\/algorithms\/rule-explanations/);
  assert.match(app, /\/api\/v1\/admin\/algorithms\/threshold-matrix/);
  assert.doesNotMatch(app, /\/api\/v1\/admin\/diagnosis\/replay/);
  assert.doesNotMatch(app, /threshold-versions/);
  assert.match(app, /function renderAlgorithmLibrary/);
  assert.match(app, /function renderRuleExplanations/);
  assert.match(app, /function renderThresholdGroups/);
  assert.match(app, /function setupGovernanceDomains/);
  assert.match(app, /function selectGovernanceDomain/);
  assert.match(app, /function governanceDomainItems/);
  assert.match(app, /function thresholdGroupDomain/);
  assert.match(app, /function setupGovernanceTabs/);
  assert.match(app, /function selectGovernanceTab/);
  assert.match(app, /function selectThresholdGroup/);
  assert.match(app, /function updateThresholdDraftEntry/);
  assert.doesNotMatch(app, /thresholdMatrixOwner/);
  assert.doesNotMatch(app, /function runDiagnosisReplay/);
  assert.doesNotMatch(app, /function renderReplayDrilldown/);
  assert.doesNotMatch(app, /function toggleReplayDrilldown/);
  assert.match(app, /function saveThresholdMatrix/);
});

test('threshold matrix uses dense duty-table styling', () => {
  assert.match(css, /\.governance-layout/);
  assert.match(css, /\.governance-domain-switch/);
  assert.match(css, /\.governance-domain-button/);
  assert.match(css, /\.governance-domain-button\[data-governance-domain="weather-systems"\]/);
  assert.match(css, /\.governance-domain-button\[data-governance-domain="risk-diagnosis"\]/);
  assert.match(css, /\.governance-domain-summary/);
  assert.match(css, /\.governance-tabs/);
  assert.match(css, /\.governance-panel/);
  assert.match(css, /\.rule-explanation-panel/);
  assert.match(css, /\.rule-threshold-chip/);
  assert.match(css, /\.threshold-matrix/);
  assert.match(css, /\.threshold-workbench/);
  assert.match(css, /\.threshold-group-list/);
  assert.match(css, /\.threshold-group-button/);
  assert.match(css, /\.version-toolbar/);
  assert.doesNotMatch(css, /\.replay-panel/);
  assert.doesNotMatch(css, /\.replay-summary/);
  assert.doesNotMatch(css, /\.replay-drilldown/);
  assert.doesNotMatch(css, /\.replay-drill-trace/);
});

test('risk threshold matrix separates scoring factors from region extraction parameters', () => {
  assert.match(app, /function thresholdEntrySection/);
  assert.match(app, /function thresholdSectionLabel/);
  assert.match(app, /格点评分因子/);
  assert.match(app, /风险区生成规则/);
  assert.match(app, /score_threshold/);
  assert.match(app, /high_score_threshold/);
  assert.match(app, /min_area_grid_points/);
  assert.match(app, /max_objects/);
  assert.match(css, /\.threshold-section-row/);
  assert.match(css, /\.threshold-section-title/);
});

test('threshold matrix uses forecaster-facing names and guidance', () => {
  assert.match(html, />物理量 \/ 参数</);
  assert.match(html, />业务判断</);
  assert.match(html, />参考阈值</);
  assert.match(html, />满分跨度</);
  assert.doesNotMatch(html, />尺度</);
  assert.match(html, /id="thresholdMatrixGuide"/);
  assert.match(html, /参考阈值决定从哪里开始计分/);
  assert.match(app, /function thresholdOperatorLabel/);
  assert.match(app, /越高越有利/);
  assert.match(app, /越低越有利/);
  assert.match(app, /贡献权重/);
  assert.match(app, /分项权重/);
  assert.match(css, /\.threshold-guide/);
  assert.match(css, /\.threshold-column-hint/);
});

test('algorithm library uses compact non-redundant risk cards', () => {
  assert.match(app, /function algorithmMetaItems/);
  assert.match(app, /function algorithmOutputItems/);
  assert.match(app, /algorithm-method-text/);
  assert.match(app, /algorithm-contract-rail/);
  assert.match(app, /格点评分 \/ 风险区提取/);
  assert.doesNotMatch(app, /chips: \[chain\.target, chain\.method\]/);
  assert.doesNotMatch(app, /class="algorithm-flow"/);
  assert.match(css, /\.algorithm-method-text/);
  assert.match(css, /\.algorithm-contract-rail/);
});

test('rule explanations render risk composition outside threshold matrix', () => {
  assert.match(app, /function renderRuleComposition/);
  assert.match(app, /合成方式/);
  assert.match(app, /composition\.channels/);
  assert.match(app, /composition\.label/);
  assert.match(app, /thresholdOperatorLabel\(entry\.operator\)/);
  assert.match(css, /\.rule-composition/);
  assert.doesNotMatch(app, /risk_precip_short_duration_heavy_rain_score", 0\.50/);
  assert.doesNotMatch(app, /risk_conv_short_duration_heavy_rain_score", 0\.50/);
});

test('algorithm governance filters assets rules and thresholds by domain', () => {
  assert.match(app, /state\.governanceDomain/);
  assert.match(app, /weather-systems/);
  assert.match(app, /risk-diagnosis/);
  assert.match(app, /const GOVERNANCE_DOMAINS/);
  assert.match(app, /ruleDomain\(section\) === state\.governanceDomain/);
  assert.match(app, /thresholdGroupDomain\(entry\.group\) === state\.governanceDomain/);
  assert.match(app, /RISK_THRESHOLD_GROUPS/);
  assert.match(app, /持续性强降水/);
  assert.match(app, /短时强降水/);
  assert.match(app, /雷暴大风\/下击暴流/);
  assert.match(app, /旋转风暴\/超级单体潜势/);
  assert.doesNotMatch(app, /SUPPORTING_THRESHOLD_GROUPS/);
  assert.doesNotMatch(app, /强降水风险证据/);
  assert.doesNotMatch(app, /强对流风险证据/);
  assert.doesNotMatch(app, /动力抬升证据/);
  assert.doesNotMatch(app, /雨雪相态证据/);
  assert.doesNotMatch(app, /heavy_rain_evidence/);
  assert.doesNotMatch(app, /convection_evidence/);
  assert.doesNotMatch(app, /dynamic_lift/);
  assert.doesNotMatch(app, /precipitation_phase/);
  assert.match(app, /chain\.governance_domain === 'risk-diagnosis'/);
  assert.match(app, /system\.governance_domain === 'weather-systems'/);
});
