const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const mapHtml = fs.readFileSync('frontend/map.html', 'utf8');
const mapJs = fs.readFileSync('frontend/map.js', 'utf8');
const mapCss = fs.readFileSync('frontend/map.css', 'utf8');

test('map feature toggles focus on primary weather systems', () => {
  assert.doesNotMatch(mapJs, /\['low_pressure_convergence', '低压辐合区'\]/);
  assert.doesNotMatch(mapJs, /\['high_pressure_divergence', '高压辐散区'\]/);
  assert.match(mapJs, /\['low_level_convergence', '低层辐合区'\]/);
  assert.match(mapJs, /\['upper_divergence', '高空辐散区'\]/);
});

test('map carries extended weather system types without global prototype patches', () => {
  assert.doesNotMatch(mapHtml, /weather-system-frontend-extension/);
  assert.doesNotMatch(mapJs, /Array\.prototype/);
  assert.doesNotMatch(mapJs, /Object\.entries =/);
  assert.doesNotMatch(mapJs, /Object\.fromEntries =/);
  assert.match(mapJs, /\['shear_line', '切变线'\]/);
  assert.match(mapJs, /\['upper_jet', '高空急流'\]/);
  assert.match(mapJs, /\['low_level_convergence_axis', '低层辐合轴'\]/);
  assert.match(mapJs, /upper_jet: 'line'/);
});

test('map front axis display follows classified front algorithm output', () => {
  assert.match(mapJs, /\['front_candidate', '锋面轴线'\]/);
  assert.match(mapJs, /frontTypeColors/);
  assert.match(mapJs, /frontTypeColorExpression/);
  assert.match(mapJs, /\['get', 'front_type'\]/);
  assert.match(mapJs, /front_type_label/);
  assert.match(mapJs, /classification_reason/);
  assert.match(mapJs, /front_motion_label/);
});

test('map feature loading can use one NAFP features request for the selected types', () => {
  assert.match(mapJs, /buildNafpFeaturesUrl/);
  assert.match(mapJs, /async function loadNafpFeatures\(selected, fh, featureLoadToken\)/);
  assert.match(mapJs, /buildNafpFeaturesUrl\(selected, selectedPointDataCode\(\), selectedPointRunTime\(\), fh, Date\.now\(\)\)/);
  assert.match(mapJs, /if \(shouldUseNafpLayerSource\(\)\) \{\s*await loadNafpFeatures\(selected, fh, featureLoadToken\);\s*return;\s*\}/);
});

test('map NAFP feature loading defaults to primary weather systems for display', () => {
  assert.match(mapJs, /primaryFeatureCollection/);
  assert.match(mapJs, /const displayFc = primaryFeatureCollection\(fc\)/);
  assert.match(mapJs, /const smoothedFc = smoothFeatureCollectionForDisplay\(displayFc\)/);
  assert.match(mapJs, /map\.getSource\(FEATURE_SOURCE_ID\)\.setData\(smoothedFc\)/);
  assert.match(mapJs, /displayFc\.properties\?\.displayed_features/);
});

test('map smooths NAFP weather feature geometry only for display', () => {
  assert.match(mapJs, /smoothFeatureCollectionForDisplay/);
  assert.match(mapJs, /const smoothedFc = smoothFeatureCollectionForDisplay\(displayFc\)/);
  assert.match(mapJs, /map\.getSource\(FEATURE_SOURCE_ID\)\.setData\(smoothedFc\)/);
  assert.match(mapJs, /state\.features = displayFc\.features \|\| \[\]/);
  assert.match(mapJs, /'line-cap': 'round'/);
  assert.match(mapJs, /'line-join': 'round'/);
});

test('map precomputes NAFP situation cache before weather system toggles need it', () => {
  assert.match(mapJs, /async function precomputeNafpSituation\(forecastHour = state\.forecastHour\)/);
  assert.match(mapJs, /postEnvelope\('\/api\/v1\/diagnosis\/nafp\/precompute'/);
  assert.match(mapJs, /forecast_hours: \[Number\(forecastHour\)\]/);
  assert.match(mapJs, /async function waitForNafpPrecompute\(forecastHour\)/);
  assert.match(mapJs, /await waitForNafpPrecompute\(fh\)/);
  assert.match(mapJs, /scheduleNafpSituationPrecompute\(\)/);
});

test('map feature checkboxes reload weather systems immediately on change', () => {
  assert.doesNotMatch(mapHtml, /id="btnLoadFeatures"/);
  assert.match(mapJs, /async function handleFeatureToggleChange\(event\)/);
  assert.match(mapJs, /event\.target\.matches\('#featureToggles input\[type="checkbox"\]'\)/);
  assert.doesNotMatch(mapJs, /riskFeatureToggles'\)\.addEventListener\('change', handleFeatureToggleChange\)/);
  assert.match(mapJs, /await loadFeatures\(\)/);
  assert.match(mapJs, /featureToggles'\)\.addEventListener\('change', handleFeatureToggleChange\)/);
});

test('map ignores stale weather-system loads after toggles are cleared', () => {
  assert.match(mapJs, /featureLoadToken: 0/);
  assert.match(mapJs, /function clearWeatherFeatures[\s\S]*state\.featureLoadToken \+= 1/);
  assert.match(mapJs, /const featureLoadToken = \+\+state\.featureLoadToken/);
  assert.match(mapJs, /loadNafpFeatures\(selected, fh, featureLoadToken\)/);
  assert.match(mapJs, /if \(featureLoadToken !== state\.featureLoadToken\) return;[\s\S]*primaryFeatureCollection/);
  assert.match(mapJs, /const fc = mergeFeatureCollections\(responses\);[\s\S]*if \(featureLoadToken !== state\.featureLoadToken\) return;/);
});

test('map feature detail formats structured NAFP evidence entries without data paths', () => {
  assert.match(mapJs, /function featureEvidenceLine\(item\)/);
  assert.match(mapJs, /item\.entry_id/);
  assert.match(mapJs, /item\.signal/);
  assert.doesNotMatch(mapJs, /source_path/);
  assert.doesNotMatch(mapJs, /source_paths/);
  assert.doesNotMatch(mapJs, /feature-source-path/);
  assert.doesNotMatch(mapJs, /area-risk-source-list/);
});

test('map feature click renders an operational quality and evidence card', () => {
  assert.match(mapJs, /function renderFeatureDetailCard\(props\)/);
  assert.match(mapJs, /featureQuality\(props\)/);
  assert.match(mapJs, /rankFeatureEvidence\(evidence\)/);
  assert.match(mapJs, /class="object-quality-strip/);
  assert.match(mapJs, /class="feature-evidence-list"/);
  assert.match(mapJs, /showObjectHtmlDetail\('对象详情', renderFeatureDetailCard\(props\)\)/);
});

test('map object detail auto-focuses the evidence card after feature selection', () => {
  assert.match(mapJs, /function focusObjectDetailPanel\(\)/);
  assert.match(mapJs, /panel\.scrollTo\(\{/);
  assert.match(mapJs, /showObjectHtmlDetail[\s\S]*focusObjectDetailPanel\(\);/);
});

test('map object detail gives the analysis panel enough room for evidence review', () => {
  assert.match(mapJs, /analysis-panel'\)\?\.classList\.add\('detail-focused'\)/);
  assert.match(mapCss, /\.analysis-panel\.detail-focused[\s\S]*bottom: 18px/);
  assert.match(mapCss, /\.analysis-panel\.detail-focused[\s\S]*max-height: none/);
});

test('map object detail shifts the legend away from the evidence panel', () => {
  assert.match(mapJs, /mapLegend'\)\?\.classList\.add\('detail-shifted'\)/);
  assert.match(mapCss, /\.map-legend\.detail-shifted[\s\S]*left: 408px/);
});

test('map page omits the weather object index controls', () => {
  assert.doesNotMatch(mapHtml, /id="featureIndexTypeFilter"/);
  assert.doesNotMatch(mapHtml, /id="featureIndexQualityFilter"/);
  assert.doesNotMatch(mapHtml, /id="featureIndexList"/);
  assert.doesNotMatch(mapHtml, /对象索引/);
  assert.match(mapJs, /function renderFeatureIndex\(\)/);
  assert.match(mapJs, /if \(!list \|\| !summary\) return/);
});

test('map object index can locate an object and open its evidence card', () => {
  assert.match(mapJs, /function locateFeatureById\(featureId\)/);
  assert.match(mapJs, /featureGeometryBounds\(feature\)/);
  assert.match(mapJs, /map\.fitBounds/);
  assert.match(mapJs, /selectFeature\(feature, center\)/);
  assert.match(mapJs, /loadNafpFeatures[\s\S]*renderFeatureIndex\(\);/);
  assert.match(mapJs, /clearWeatherFeatures[\s\S]*renderFeatureIndex\(\);/);
});

test('map feature selection links objects to their diagnostic evidence layer', () => {
  assert.match(mapJs, /recommendedFeatureLayer/);
  assert.match(mapJs, /async function syncLayerForFeature\(props\)/);
  assert.match(mapJs, /recommendedFeatureLayer\(props, Object\.keys\(state\.layers\)\)/);
  assert.match(mapJs, /\$\('layerSelect'\)\.value = suggestion\.layerId/);
  assert.match(mapJs, /await loadLayer\(\{ fitBounds: false \}\)/);
  assert.match(mapJs, /void syncLayerForFeature\(props\)/);
});
