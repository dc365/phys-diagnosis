const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('frontend/map.html', 'utf8');
const css = fs.readFileSync('frontend/map.css', 'utf8');
const mapJs = fs.readFileSync('frontend/map.js', 'utf8');
const contourGlyphPath = 'frontend/vendor/maplibre-fonts/Noto Sans Regular/0-255.pbf';

test('map page keeps the meteorological map workbench structure', () => {
  assert.match(html, /class="skip-link" href="#main-content"/);
  assert.match(html, /<main id="main-content" class="map-stage">/);
  assert.match(html, /class="layer-panel" aria-label="要素、风险与天气系统"/);
  assert.match(html, /id="btnClearOverlays"/);
  assert.match(html, /class="timeline-bar" aria-label="预报时效时间轴"/);
});

test('map page cache-busts static assets after interface changes', () => {
  assert.match(html, /href="\/static\/map\.css\?v=layer-groups-20260628"/);
  const utilsVersion = html.match(/src="\/static\/maplibre-utils\.js\?v=([^"]+)"/)?.[1];
  const mapVersion = html.match(/src="\/static\/map\.js\?v=([^"]+)"/)?.[1];
  assert.equal(utilsVersion, 'map-feature-race-20260626');
  assert.equal(mapVersion, 'layer-groups-20260628');
});

test('map page bundles MapLibre and avoids legacy public basemap dependencies', () => {
  assert.match(html, /href="\/static\/vendor\/maplibre-gl\/maplibre-gl\.css\?v=[^"]+"/);
  assert.match(html, /src="\/static\/vendor\/maplibre-gl\/maplibre-gl\.js\?v=[^"]+"/);
  assert.doesNotMatch(html, /https?:\/\//);
  assert.doesNotMatch(mapJs, /tile\.openstreetmap\.org|demotiles\.maplibre\.org|unpkg\.com/);
  assert.match(mapJs, /glyphs: '\/static\/vendor\/maplibre-fonts\/\{fontstack\}\/\{range\}\.pbf'/);
  assert.match(mapJs, /const BASEMAP_LOCAL_TEMPLATE = '\/static\/basemaps\/china\/\{z\}\/\{x\}\/\{y\}\.png'/);
  assert.match(mapJs, /function applyBaseMap\(\)/);
  assert.match(mapJs, /if \(id === 'offline'\)[\s\S]*无外网请求/);
  assert.match(mapJs, /tdt-vector/);
  assert.match(mapJs, /tianditu\.gov\.cn/);
});

test('map page vendors the glyph PBF needed by contour labels', () => {
  const stat = fs.statSync(contourGlyphPath);
  assert.ok(stat.size > 1000, `glyph file is unexpectedly small: ${stat.size}`);
});

test('map page configures Tianditu as the default demo basemap', () => {
  assert.match(html, /window\.WEATHER_MAP_CONFIG = \{/);
  assert.match(html, /basemap: 'tdt-vector'/);
  assert.match(html, /tiandituToken: '[0-9a-f]{32}'/);
});

test('map page exposes selectable local and China-accessible basemaps', () => {
  assert.match(html, /id="basemapSelect"/);
  assert.match(html, /<option value="offline" selected>离线简图<\/option>/);
  assert.match(html, /<option value="local-xyz">内网瓦片<\/option>/);
  assert.match(html, /<option value="tdt-vector">天地图矢量<\/option>/);
  assert.match(html, /<option value="tdt-image">天地图影像<\/option>/);
  assert.match(css, /\.basemap-field select/);
  assert.match(mapJs, /function setupBasemapControl\(\)/);
  assert.match(mapJs, /function localTileTemplate\(\)/);
  assert.match(mapJs, /function tiandituToken\(\)/);
  assert.match(mapJs, /basemapSelect'\)\.addEventListener\('change', applyBaseMap\)/);
});

test('map data category selector keeps forecast and sounding at the top level', () => {
  assert.match(html, /id="dataCategorySelect"/);
  assert.match(html, /<option value="forecast" selected>数值模式预报<\/option>/);
  assert.match(html, /<option value="sounding">实况<\/option>/);
  assert.ok(html.indexOf('id="dataCategorySelect"') < html.indexOf('class="layer-panel"'));
  assert.ok(html.indexOf('id="soundingFileSelect"') < html.indexOf('class="layer-panel"'));
  assert.doesNotMatch(html, /class="panel-subsection sounding-panel"/);
  assert.match(mapJs, /function selectedDataCategory\(\)/);
  assert.match(mapJs, /function syncDataCategoryControls\(\)/);
  assert.match(mapJs, /dataCategorySelect'\)\.addEventListener\('change'/);
});

test('map page does not expose demo-data generation controls', () => {
  assert.doesNotMatch(html, /示例数据/);
  assert.doesNotMatch(html, /id="btnDemo"/);
  assert.doesNotMatch(mapJs, /generateDemo/);
  assert.doesNotMatch(mapJs, /btnDemo/);
  assert.doesNotMatch(mapJs, /\/api\/jobs\/generate-demo/);
});

test('product run selector is hidden unless the product data source is selected', () => {
  assert.match(html, /class="control-field run-field forecast-control" hidden/);
  assert.match(html, /class="layer-source-control" hidden/);
  assert.match(html, />诊断产品</);
  assert.match(mapJs, /function syncProductRunVisibility\(\)/);
  assert.match(mapJs, /field\.hidden = selectedDataCategory\(\) === 'sounding' \|\| shouldUseNafpLayerSource\(\)/);
  assert.match(mapJs, /syncProductRunVisibility\(\);\s*if \(shouldUseNafpLayerSource\(\)\)/);
});

test('map model selector uses configured data source labels', () => {
  assert.match(html, /id="pointDataCodeSelect"/);
  assert.match(html, /aria-label="模式"/);
  assert.doesNotMatch(html, /id="modelSelect"/);
  assert.doesNotMatch(html, /ECMWF/);
  assert.doesNotMatch(html, /point-data-field" hidden/);
  assert.match(mapJs, /const DEFAULT_POINT_DATA_CODE = 'NAFP_ECTHIN_NC'/);
  assert.match(mapJs, /function selectedPointDataCode\(\)/);
  assert.match(mapJs, /function dataSourceLabel/);
  assert.match(mapJs, /option\.textContent = dataSourceLabel\(item\)/);
});

test('map css makes the map the primary canvas with right layers and bottom timeline', () => {
  assert.match(css, /\.app-shell[\s\S]*grid-template-rows: minmax\(0, 1fr\) 92px/);
  assert.match(css, /\.topbar[\s\S]*position: absolute/);
  assert.match(css, /\.layer-panel[\s\S]*right: 12px/);
  assert.match(css, /\.layer-panel[\s\S]*bottom: 14px/);
  assert.match(css, /\.timeline-bar[\s\S]*grid-template-columns: auto auto minmax\(0, 1fr\) auto/);
  assert.match(css, /--sky-canvas/);
  assert.match(css, /--cloud-panel-raised/);
  assert.match(css, /--radar-cyan/);
});

test('layer chips keep readable labels above generated preview art', () => {
  assert.match(mapJs, /function createLayerChipButton/);
  assert.match(mapJs, /const label = document\.createElement\('span'\)/);
  assert.match(css, /\.layer-chip > span[\s\S]*z-index: 1/);
});

test('map element chips are grouped by meteorological level', () => {
  assert.match(html, /id="layerChips" class="layer-chip-groups"/);
  assert.match(html, /id="riskLayerChips" class="layer-chips"/);
  assert.match(mapJs, /const ELEMENT_LAYER_LEVELS = \[/);
  assert.match(mapJs, /label: '地面'/);
  assert.match(mapJs, /label: '850hPa'/);
  assert.match(mapJs, /label: '500hPa'/);
  assert.match(mapJs, /label: '跨层\/指数'/);
  assert.match(mapJs, /function elementLayerLevelKey/);
  assert.match(mapJs, /renderLayerChipGroup\('layerChips', isElementLayer, \{ groupByLevel: true \}\)/);
  assert.match(css, /\.layer-chip-groups/);
  assert.match(css, /\.layer-level-title/);
});

test('map controls remain visible on the light workbench chrome', () => {
  assert.match(css, /\.maplibregl-ctrl-group[\s\S]*background: var\(--cloud-panel-raised\)/);
  assert.match(css, /\.maplibregl-ctrl-group button \.maplibregl-ctrl-icon[\s\S]*filter: none/);
});

test('weather feature overlays can be cleared completely', () => {
  assert.match(mapJs, /function clearMapOverlays\(\)/);
  assert.match(mapJs, /function clearFeatureSelection\(\)/);
  assert.match(mapJs, /btnClearOverlays'\)\.addEventListener\('click', clearMapOverlays\)/);
  assert.match(mapJs, /未选择要素，仅显示地图/);
  assert.match(mapJs, /未选择天气系统，仅显示地图/);
  assert.match(mapJs, /setData\(\{ type: 'FeatureCollection', features: \[\] \}\)/);
});

test('right panel omits risk object and object index blocks', () => {
  assert.match(html, /id="riskLayerChips"/);
  assert.match(html, /id="featureToggles"/);
  assert.doesNotMatch(html, /风险对象/);
  assert.doesNotMatch(html, /id="riskFeatureToggles"/);
  assert.doesNotMatch(html, /对象索引/);
  assert.doesNotMatch(html, /id="featureIndexTypeFilter"/);
  assert.doesNotMatch(html, /id="featureIndexQualityFilter"/);
  assert.doesNotMatch(html, /id="featureIndexList"/);
  assert.doesNotMatch(html, /id="btnLoadFeatures"/);
  assert.doesNotMatch(html, /id="btnClearFeatures"/);
});

test('right risk panel exposes area risk as an independent map function', () => {
  assert.match(html, /<h2>风险<\/h2>[\s\S]*<strong class="panel-subtitle">风险图层<\/strong>[\s\S]*id="riskLayerChips"/);
  assert.match(html, /<strong class="panel-subtitle">区域风险<\/strong>/);
  assert.match(html, /id="areaRiskScopeSelect"/);
  assert.match(html, /id="areaRiskModeSelect"/);
  assert.match(html, /id="areaRiskTypeSelect"/);
  assert.match(html, /id="btnLoadAreaRisk"/);
  assert.match(html, /id="areaRiskSummary"/);
  assert.match(html, /id="areaRiskList"/);
  assert.doesNotMatch(html, /id="areaRiskStartTime"/);
  assert.doesNotMatch(html, /id="areaRiskEndTime"/);
  assert.match(mapJs, /\/api\/v1\/diagnosis\/nafp\/areas/);
  assert.match(mapJs, /\/api\/v1\/diagnosis\/nafp\/area-risks/);
  assert.match(mapJs, /function ensureAreaRiskLayers\(\)/);
  assert.match(mapJs, /async function loadAreaRisks/);
  assert.match(mapJs, /function selectAreaRiskFeature/);
});

test('weather system toggles use the same colors as map feature layers', () => {
  assert.match(mapJs, /function featureColor\(properties\)/);
  assert.match(mapJs, /const color = featureColor\(type\)/);
  assert.match(mapJs, /input\.checked = false/);
  assert.doesNotMatch(mapJs, /input\.checked = true/);
  assert.match(mapJs, /className = `feature-swatch feature-swatch-\$\{featureLegendKind\(type\)\}`/);
  assert.match(mapJs, /style\.setProperty\('--feature-color', color\)/);
  assert.match(css, /\.feature-swatch[\s\S]*background: var\(--feature-color\)/);
  assert.match(css, /\.feature-swatch-line[\s\S]*height: 3px/);
  assert.match(css, /\.feature-swatch-area[\s\S]*border: 1px solid var\(--feature-color\)/);
});

test('map page exposes contour overlay controls and source wiring', () => {
  assert.match(html, /id="contourToggle"/);
  assert.match(html, />等值线</);
  assert.match(mapJs, /const CONTOUR_SOURCE_ID = 'diagnostic-contours'/);
  assert.match(mapJs, /function ensureContourLayer\(\)/);
  assert.match(mapJs, /function loadContours\(\)/);
  assert.match(mapJs, /buildLayerContourUrl\(layer, runId, fh, Date\.now\(\)\)/);
});

test('grid palette keeps administrative labels readable above the color field', () => {
  assert.match(mapJs, /const REFERENCE_OVERLAY_LAYER_ID = 'map-reference-overlay'/);
  assert.match(mapJs, /const GRID_FILL_OPACITY = 0\.5/);
  assert.match(mapJs, /ensureGridLayer\(\);\s*applyBaseMap\(\);\s*ensureReferenceOverlayLayer\(\);/);
  assert.match(mapJs, /'fill-opacity': GRID_FILL_OPACITY/);
  assert.match(mapJs, /'fill-antialias': false/);
  assert.match(mapJs, /function ensureReferenceOverlayLayer\(\)/);
  assert.match(mapJs, /renderChinesePlaceLabels\(\)/);
  assert.doesNotMatch(mapJs, /source: 'osm'/);
});

test('contour overlay uses local MapLibre glyphs for collision-aware labels', () => {
  assert.match(mapJs, /const CONTOUR_LABEL_LAYER_ID = 'diagnostic-contour-labels'/);
  assert.match(mapJs, /const CONTOUR_LABEL_SOURCE_ID = 'diagnostic-contour-label-points'/);
  assert.match(mapJs, /const CONTOUR_LABEL_MIN_DISTANCE_DEGREES = [0-9.]+/);
  assert.match(mapJs, /const CONTOUR_LABEL_SAME_VALUE_MIN_DISTANCE_DEGREES = [0-9.]+/);
  assert.match(mapJs, /id: CONTOUR_LAYER_ID,[\s\S]*type: 'line'/);
  assert.match(mapJs, /id: CONTOUR_LABEL_LAYER_ID,[\s\S]*type: 'symbol'/);
  assert.match(mapJs, /source: CONTOUR_LABEL_SOURCE_ID/);
  assert.match(mapJs, /'text-field': \['get', 'value_text'\]/);
  assert.match(mapJs, /'text-font': \['Noto Sans Regular'\]/);
  assert.match(mapJs, /function contourLabelFeatureCollection\(collection\)/);
  assert.match(mapJs, /function contourLabelBounds\(\)/);
  assert.match(mapJs, /function contourCandidateDistance\(first, second\)/);
  assert.match(mapJs, /function contourLabelTooClose\(candidate, selected\)/);
  assert.match(mapJs, /function selectContourLabelCandidates\(candidates\)/);
  assert.match(mapJs, /function refreshContourLabelSource\(\)/);
  assert.match(mapJs, /map\.on\('moveend', refreshContourLabelSource\)/);
  assert.match(mapJs, /contours: null/);
  assert.match(mapJs, /state\.contours = contours/);
  assert.match(mapJs, /map\.getSource\(CONTOUR_LABEL_SOURCE_ID\)\.setData\(contourLabelFeatureCollection\(contours\)\)/);
  assert.match(mapJs, /map\.on\('click', CONTOUR_LAYER_ID/);
  assert.match(mapJs, /function selectContour\(feature, lngLat\)/);
  assert.doesNotMatch(mapJs, /\.sort\(\(a, b\) => b\.length - a\.length\)\s*\.slice\(0, MAX_CONTOUR_LABELS\)/);
});

test('sounding z500 contour display is line-priority and NMC-like', () => {
  assert.match(mapJs, /const SOUNDING_GRID_FILL_OPACITY = 0\.18/);
  assert.match(mapJs, /const Z500_CONTOUR_COLOR = '#3155d4'/);
  assert.match(mapJs, /function contourColorExpression\(\)/);
  assert.match(mapJs, /'line-color': contourColorExpression\(\)/);
  assert.match(mapJs, /'line-cap': 'round'/);
  assert.match(mapJs, /'line-join': 'round'/);
  assert.match(mapJs, /map\.setPaintProperty\(GRID_FILL_LAYER_ID, 'fill-opacity', SOUNDING_GRID_FILL_OPACITY\)/);
  assert.match(mapJs, /map\.setPaintProperty\(GRID_FILL_LAYER_ID, 'fill-opacity', GRID_FILL_OPACITY\)/);
});

test('contour values avoid dense DOM marker labels', () => {
  assert.doesNotMatch(mapJs, /contourLabelMarkers/);
  assert.doesNotMatch(mapJs, /function renderContourLabels/);
  assert.doesNotMatch(mapJs, /contour-value-label/);
  assert.doesNotMatch(css, /\.contour-value-label/);
});
