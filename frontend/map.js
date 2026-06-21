const DEFAULT_BOUNDS = [70, 15, 140, 55];
const DEFAULT_CENTER = [105, 35];
const DEFAULT_POINT_DATA_CODE = 'NAFP_ECTHIN_NEW_NC';
const GRID_SOURCE_ID = 'diagnostic-grid';
const GRID_FILL_LAYER_ID = 'diagnostic-grid-fill';
const REFERENCE_OVERLAY_LAYER_ID = 'map-reference-overlay';
const GRID_FILL_OPACITY = 0.34;
const CONTOUR_SOURCE_ID = 'diagnostic-contours';
const CONTOUR_LAYER_ID = 'diagnostic-contour-lines';
const CONTOUR_LABEL_LAYER_ID = 'diagnostic-contour-labels';
const FEATURE_SOURCE_ID = 'weather-features';
const FEATURE_LAYER_IDS = {
  polygonFill: 'weather-feature-polygons',
  polygonLine: 'weather-feature-polygon-outlines',
  line: 'weather-feature-lines',
  point: 'weather-feature-points',
};

const state = {
  runs: [],
  runId: 'ecmwf_demo',
  forecastHour: 24,
  forecastHours: [],
  layerSource: 'nafp',
  layers: {},
  currentBounds: DEFAULT_BOUNDS,
  features: [],
  selectedFeatureId: '',
  mapReady: false,
  pointProbeActive: false,
  pointDataSources: [],
  pointDataCode: DEFAULT_POINT_DATA_CODE,
  pointRunTime: '',
  pointRunTimes: [],
};

const weatherSystemFeatureTypes = [
  ['high', '高压中心'], ['low', '低压中心'], ['subtropical_high', '副高588区'],
  ['low_pressure_convergence', '低压辐合区'], ['high_pressure_divergence', '高压辐散区'],
  ['trough', '槽线候选'], ['ridge', '脊线候选'], ['low_level_convergence', '低层辐合区'],
  ['upper_divergence', '高空辐散区'], ['low_level_jet', '低空急流'],
  ['moisture_transport', '水汽输送带'], ['front_candidate', '锋面候选'],
];

const riskFeatureTypes = [
  ['heavy_rain_risk', '强降水潜势'], ['convection_risk', '强对流潜势'],
  ['persistent_heavy_rain_risk', '持续性强降水'],
  ['short_duration_heavy_rain_risk', '短时强降水'],
  ['thunderstorm_gale_risk', '雷暴大风/下击暴流'],
  ['hail_risk', '冰雹'],
  ['rotating_storm_risk', '旋转风暴/超级单体潜势'],
  ['severe_convection_composite_risk', '强对流综合风险'],
];

const featureTypes = [...weatherSystemFeatureTypes, ...riskFeatureTypes];

const featureColors = {
  high: '#e03131',
  low: '#1c7ed6',
  subtropical_high: '#f59f00',
  low_pressure_convergence: '#0b7285',
  high_pressure_divergence: '#e8590c',
  trough: '#7c3aed',
  ridge: '#f08c00',
  low_level_convergence: '#0ca678',
  upper_divergence: '#15aabf',
  low_level_jet: '#d9480f',
  moisture_transport: '#228be6',
  front_candidate: '#495057',
  heavy_rain_risk: '#c92a2a',
  convection_risk: '#9c36b5',
  persistent_heavy_rain_risk: '#b02a37',
  short_duration_heavy_rain_risk: '#1971c2',
  thunderstorm_gale_risk: '#5f3dc4',
  hail_risk: '#0b7285',
  rotating_storm_risk: '#e67700',
  severe_convection_composite_risk: '#862e9c',
};

const featureLegendKinds = {
  high: 'point',
  low: 'point',
  trough: 'line',
  ridge: 'line',
  low_level_jet: 'line',
  moisture_transport: 'line',
  front_candidate: 'line',
};

const featureTypeNames = Object.fromEntries(featureTypes);
const pointTargetNames = {
  heavy_rain_potential: '强降水',
  convection_potential: '强对流',
  dynamic_lift_potential: '动力抬升',
  precipitation_phase: '雨雪相态',
  persistent_heavy_rain: '持续性强降水',
  short_duration_heavy_rain: '短时强降水',
  thunderstorm_gale: '雷暴大风/下击暴流',
  hail: '冰雹',
  rotating_storm_or_supercell: '旋转风暴/超级单体潜势',
  severe_convection_composite: '强对流综合风险',
  persistent_heavy_rain_risk: '持续性强降水',
  short_duration_heavy_rain_risk: '短时强降水',
  thunderstorm_gale_risk: '雷暴大风/下击暴流',
  hail_risk: '冰雹',
  rotating_storm_risk: '旋转风暴/超级单体潜势',
  severe_convection_composite_risk: '强对流综合风险',
};
const pointLevelNames = {
  high: '高',
  moderate: '中',
  low: '低',
};

const pointRiskChannels = [
  {
    id: 'precipitation',
    label: '强降水风险',
    hazards: ['persistent_heavy_rain', 'short_duration_heavy_rain'],
  },
  {
    id: 'severe_convection',
    label: '强对流风险',
    hazards: ['short_duration_heavy_rain', 'thunderstorm_gale', 'hail', 'rotating_storm_or_supercell'],
  },
];

const legacyRiskLayerIds = new Set(['heavy_rain_score', 'convection_score']);

const layerPalettes = {
  score: ['#fff7bc', '#fec44f', '#fb6a4a', '#bd0026'],
  moisture: ['#edf8fb', '#b2e2e2', '#66c2a4', '#238b45'],
  diverging: ['#2166ac', '#f7f7f7', '#b2182b'],
  default: ['#f7fbff', '#9ecae1', '#3182bd', '#08519c'],
};

const chinesePlaceLabels = [
  ['中国', 104, 35],
  ['蒙古', 103, 47],
  ['俄罗斯', 100, 55],
  ['哈萨克斯坦', 70, 48],
  ['印度', 78, 22],
  ['缅甸', 96, 20],
  ['泰国', 101, 15],
  ['越南', 108, 16],
  ['菲律宾', 122, 13],
  ['日本', 138, 37],
  ['韩国', 128, 36],
];

const {
  buildLayerContourUrl,
  buildColorRampExpression,
  buildLayerGridUrl,
  buildNafpFeaturesUrl,
  buildNafpLayerContourUrl,
  buildNafpLayerGridUrl,
  buildNafpLayerMetadataUrl,
  featureDisplayLabel,
  featureGeometryBounds,
  featureIndexRows,
  featureQuality,
  forecastHourLabel,
  mergeFeatureCollections,
  metadataToBounds,
  nextForecastHour,
  rankFeatureEvidence,
  recommendedFeatureLayer,
} = window.WeatherMapUtils;

let map;
let popup;
let pointMarkers = [];
let pointProbeMarker;
let placeMarkers = [];

function $(id) { return document.getElementById(id); }
function status(msg) { $('status').textContent = msg; }

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  return await r.json();
}

async function postEnvelope(url, payload) {
  const body = await api(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (body?.code !== 0) throw new Error(body?.msg || '接口返回异常');
  return body.data;
}

async function getEnvelope(url) {
  const body = await api(url);
  if (body?.code !== 0) throw new Error(body?.msg || '接口返回异常');
  return body.data;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function colorMatchExpression() {
  const expression = ['match', ['get', 'feature_type']];
  Object.entries(featureColors).forEach(([type, color]) => expression.push(type, color));
  expression.push('#333333');
  return expression;
}

function featureLegendKind(type) {
  return featureLegendKinds[type] || 'area';
}

function isRiskLayer(layerId) {
  return legacyRiskLayerIds.has(layerId) || String(layerId || '').startsWith('risk_');
}

function isElementLayer(layerId) {
  return !isRiskLayer(layerId);
}

function createBaseStyle() {
  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      osm: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors',
      },
    },
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: { 'background-color': '#edf4fb' },
      },
      {
        id: 'osm',
        type: 'raster',
        source: 'osm',
        paint: {
          'raster-opacity': 0.56,
          'raster-saturation': -0.45,
          'raster-contrast': -0.08,
          'raster-brightness-min': 0.05,
          'raster-brightness-max': 0.92,
        },
      },
    ],
  };
}

function renderFeatureToggleGroup(boxId, items) {
  const box = $(boxId);
  if (!box) return;
  box.innerHTML = '';
  items.forEach(([type, label]) => {
    const color = featureColors[type] || '#333333';
    const el = document.createElement('label');
    el.dataset.featureType = type;

    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = type;
    input.checked = true;
    input.style.accentColor = color;

    const swatch = document.createElement('span');
    swatch.className = `feature-swatch feature-swatch-${featureLegendKind(type)}`;
    swatch.style.setProperty('--feature-color', color);
    swatch.setAttribute('aria-hidden', 'true');

    const text = document.createElement('span');
    text.className = 'feature-label';
    text.textContent = label;

    el.append(input, swatch, text);
    box.appendChild(el);
  });
}

function setupFeatureToggles() {
  renderFeatureToggleGroup('riskFeatureToggles', riskFeatureTypes);
  renderFeatureToggleGroup('featureToggles', weatherSystemFeatureTypes);
}

function appendFeatureIndexOptionGroup(select, label, items) {
  const group = document.createElement('optgroup');
  group.label = label;
  items.forEach(([type, text]) => {
    const option = document.createElement('option');
    option.value = type;
    option.textContent = text;
    group.appendChild(option);
  });
  select.appendChild(group);
}

function setupFeatureIndexControls() {
  const typeFilter = $('featureIndexTypeFilter');
  if (!typeFilter) return;
  typeFilter.innerHTML = '';
  const allOption = document.createElement('option');
  allOption.value = 'all';
  allOption.textContent = '全部类型';
  typeFilter.appendChild(allOption);
  appendFeatureIndexOptionGroup(typeFilter, '风险', riskFeatureTypes);
  appendFeatureIndexOptionGroup(typeFilter, '天气系统', weatherSystemFeatureTypes);
  renderFeatureIndex();
}

function selectedFeatureIndexFilters() {
  return {
    type: $('featureIndexTypeFilter')?.value || 'all',
    quality: $('featureIndexQualityFilter')?.value || 'all',
  };
}

function featureRowId(feature) {
  const props = feature?.properties || {};
  if (props.id) return props.id;
  const index = state.features.indexOf(feature);
  return `feature-${Math.max(0, index)}`;
}

function renderFeatureIndex() {
  const list = $('featureIndexList');
  const summary = $('featureIndexSummary');
  if (!list || !summary) return;
  const rows = featureIndexRows(state.features, selectedFeatureIndexFilters());
  list.innerHTML = '';
  summary.textContent = state.features.length
    ? `显示 ${rows.length}/${state.features.length}`
    : '尚未加载对象';

  if (!state.features.length) {
    const empty = document.createElement('div');
    empty.className = 'feature-index-empty';
    empty.textContent = '加载天气系统后生成索引';
    list.appendChild(empty);
    return;
  }
  if (!rows.length) {
    const empty = document.createElement('div');
    empty.className = 'feature-index-empty';
    empty.textContent = '当前筛选无对象';
    list.appendChild(empty);
    return;
  }

  rows.forEach((row) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `feature-index-item${row.id === state.selectedFeatureId ? ' active' : ''}`;
    button.dataset.featureId = row.id;

    const title = document.createElement('strong');
    title.textContent = featureTypeNames[row.featureType] || row.featureType;
    const badge = document.createElement('em');
    badge.className = row.qualityLevel;
    badge.textContent = row.qualityLabel;
    const meta = document.createElement('span');
    meta.textContent = `${row.label} · 置信度 ${row.scoreText}`;
    const id = document.createElement('small');
    id.textContent = row.id;

    button.append(title, badge, meta, id);
    button.addEventListener('click', () => locateFeatureById(row.id));
    list.appendChild(button);
  });
}

function featureBoundsCenter(bounds) {
  if (!Array.isArray(bounds) || bounds.length !== 4) return DEFAULT_CENTER;
  return [
    (Number(bounds[0]) + Number(bounds[2])) / 2,
    (Number(bounds[1]) + Number(bounds[3])) / 2,
  ];
}

function layerDisplayName(layerId) {
  return state.layers[layerId]?.title || layerId || '-';
}

async function syncLayerForFeature(props) {
  const suggestion = recommendedFeatureLayer(props, Object.keys(state.layers));
  if (!suggestion || !$('layerSelect')) return;
  if ($('layerSelect').value === suggestion.layerId) {
    renderLayerChips();
    status(`已联动诊断图层：${layerDisplayName(suggestion.layerId)}`);
    return;
  }
  $('layerSelect').value = suggestion.layerId;
  renderLayerChips();
  try {
    await loadLayer({ fitBounds: false });
    status(`已联动诊断图层：${layerDisplayName(suggestion.layerId)}，保留对象定位`);
  } catch (error) {
    console.warn(`feature layer sync failed: ${suggestion.layerId}`, error);
    status(`图层联动失败：${error.message}`);
  }
}

function locateFeatureById(featureId) {
  const feature = state.features.find((item) => featureRowId(item) === featureId);
  if (!feature || !map) return;
  const bounds = featureGeometryBounds(feature);
  const center = featureBoundsCenter(bounds);
  if (bounds) {
    const isPointBounds = bounds[0] === bounds[2] && bounds[1] === bounds[3];
    if (isPointBounds) {
      map.flyTo({
        center,
        zoom: Math.max(map.getZoom(), 5),
        duration: 450,
      });
    } else {
      map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
        padding: { top: 118, right: 350, bottom: 108, left: 420 },
        maxZoom: 6.2,
        duration: 520,
      });
    }
  }
  selectFeature(feature, center);
}

function renderLayerChipGroup(boxId, predicate) {
  const box = $(boxId);
  if (!box) return;
  box.innerHTML = '';
  Object.entries(state.layers).filter(([id]) => predicate(id)).forEach(([id, cfg]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `layer-chip${id === $('layerSelect').value ? ' active' : ''}`;
    const label = document.createElement('span');
    label.textContent = cfg.title || id;
    button.appendChild(label);
    button.addEventListener('click', async () => {
      $('layerSelect').value = id;
      renderLayerChips();
      await loadLayer();
    });
    box.appendChild(button);
  });
}

function renderLayerChips() {
  renderLayerChipGroup('layerChips', isElementLayer);
  renderLayerChipGroup('riskLayerChips', isRiskLayer);
}

function renderTimeline() {
  const box = $('timelineHours');
  if (!box) return;
  box.innerHTML = '';
  $('currentTimeLabel').textContent = forecastHourLabel(state.forecastHour);
  state.forecastHours.forEach((hour) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `time-chip${Number(hour) === Number(state.forecastHour) ? ' active' : ''}`;
    button.textContent = forecastHourLabel(hour);
    button.addEventListener('click', async () => {
      await setForecastHour(Number(hour));
    });
    box.appendChild(button);
  });
}

function formatPointRunTimeLabel(value) {
  const text = String(value || '');
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})/);
  if (!match) return text || '未发现时次';
  return `${match[2]}-${match[3]} ${match[4]}时`;
}

function selectedPointDataCode() {
  return $('pointDataCodeSelect')?.value || state.pointDataCode || DEFAULT_POINT_DATA_CODE;
}

function selectedPointRunTime() {
  return $('pointRunTimeSelect')?.value || state.pointRunTime || '';
}

function selectedLayerSource() {
  const source = $('layerSourceSelect')?.value || state.layerSource || 'nafp';
  return source === 'product' ? 'product' : 'nafp';
}

function shouldUseNafpLayerSource() {
  return selectedLayerSource() === 'nafp';
}

function syncProductRunVisibility() {
  const field = document.querySelector('.run-field');
  if (field) field.hidden = shouldUseNafpLayerSource();
}

function setForecastHourOptions(hours) {
  const normalized = [...new Set((hours || []).map(Number).filter(Number.isFinite))].sort((a, b) => a - b);
  const sel = $('fhSelect');
  sel.innerHTML = '';
  const options = normalized.length ? normalized : [state.forecastHour];
  let nextHour = Number(state.forecastHour);
  if (!options.includes(nextHour)) nextHour = options.includes(24) ? 24 : options[0];
  state.forecastHours = options;
  state.forecastHour = Number(nextHour);
  options.forEach((fh) => {
    const o = document.createElement('option');
    o.value = fh;
    o.textContent = forecastHourLabel(fh);
    sel.appendChild(o);
  });
  sel.value = String(state.forecastHour);
  renderTimeline();
}

function selectedPointRunInfo() {
  const sel = $('pointRunTimeSelect');
  const option = sel?.selectedOptions?.[0];
  let forecastHours = [];
  try {
    forecastHours = JSON.parse(option?.dataset.forecastHours || '[]');
  } catch (error) {
    forecastHours = [];
  }
  return {
    run_time: selectedPointRunTime(),
    forecast_hours: forecastHours.map(Number).filter(Number.isFinite),
  };
}

function syncForecastHoursFromPointRunTime() {
  const run = selectedPointRunInfo();
  setForecastHourOptions(run.forecast_hours.length ? run.forecast_hours : [state.forecastHour]);
}

function populatePointDataCodes(items, defaultCode) {
  const sel = $('pointDataCodeSelect');
  const options = items.length
    ? items
    : [{ code: DEFAULT_POINT_DATA_CODE, enabled: true }];
  sel.innerHTML = '';
  options.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.code;
    option.textContent = item.code;
    sel.appendChild(option);
  });
  const preferred = defaultCode || state.pointDataCode || DEFAULT_POINT_DATA_CODE;
  sel.value = options.some((item) => item.code === preferred) ? preferred : options[0].code;
  state.pointDataCode = sel.value;
}

function populatePointRunTimes(payload) {
  const sel = $('pointRunTimeSelect');
  const runs = payload?.run_times || [];
  state.pointRunTimes = runs;
  sel.innerHTML = '';
  if (!runs.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = '未发现时次';
    option.disabled = true;
    option.selected = true;
    sel.appendChild(option);
    state.pointRunTime = '';
    if (shouldUseNafpLayerSource()) syncForecastHoursFromPointRunTime();
    return;
  }
  runs.forEach((run) => {
    const option = document.createElement('option');
    option.value = run.run_time;
    option.textContent = formatPointRunTimeLabel(run.run_time);
    option.dataset.forecastHours = JSON.stringify(run.forecast_hours || []);
    sel.appendChild(option);
  });
  const preferred = payload?.default_run_time || state.pointRunTime || runs[0].run_time;
  sel.value = runs.some((run) => run.run_time === preferred) ? preferred : runs[0].run_time;
  state.pointRunTime = sel.value;
  if (shouldUseNafpLayerSource()) syncForecastHoursFromPointRunTime();
}

async function refreshPointRunTimes() {
  const dataCode = selectedPointDataCode();
  state.pointDataCode = dataCode;
  const payload = await getEnvelope(`/api/v1/admin/data-sources/${encodeURIComponent(dataCode)}/nafp-runs`);
  populatePointRunTimes(payload);
}

async function refreshPointDataSources() {
  try {
    const payload = await getEnvelope('/api/v1/admin/data-sources');
    const items = (payload?.items || []).filter((item) => item?.enabled !== false);
    state.pointDataSources = items;
    populatePointDataCodes(items, payload?.default_code);
    await refreshPointRunTimes();
  } catch (error) {
    state.pointDataSources = [{ code: DEFAULT_POINT_DATA_CODE, enabled: true }];
    populatePointDataCodes(state.pointDataSources, DEFAULT_POINT_DATA_CODE);
    populatePointRunTimes({ run_times: [] });
    status(`点位诊断数据源加载失败：${error.message}`);
  }
}

async function setForecastHour(hour) {
  state.forecastHour = Number(hour);
  $('fhSelect').value = String(state.forecastHour);
  renderTimeline();
  await loadLayer();
  await loadFeatures();
}

function initializeMap() {
  if (!window.maplibregl) {
    status('MapLibre 加载失败，请检查网络或 CDN 可用性');
    return;
  }

  map = new maplibregl.Map({
    container: 'map',
    style: createBaseStyle(),
    center: DEFAULT_CENTER,
    zoom: 3.3,
    minZoom: 2,
    maxZoom: 10,
    attributionControl: false,
    locale: {
      'NavigationControl.ZoomIn': '放大',
      'NavigationControl.ZoomOut': '缩小',
      'NavigationControl.ResetBearing': '重置方位',
      'AttributionControl.ToggleAttribution': '显示版权信息',
    },
  });

  popup = new maplibregl.Popup({ closeButton: false, closeOnClick: true, maxWidth: '320px' });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

  map.on('load', () => {
    state.mapReady = true;
    ensureGridLayer();
    ensureReferenceOverlayLayer();
    ensureContourLayer();
    ensureFeatureLayers();
    renderChinesePlaceLabels();
    fitCurrentBounds({ duration: 0 });
    status('MapLibre GIS 已就绪');
  });

  map.on('click', (event) => {
    if (state.pointProbeActive) diagnosePointAt(event.lngLat);
  });

  map.on('error', (event) => {
    const message = event?.error?.message || '地图资源加载异常';
    console.warn(message);
    status(`GIS 提示：${message}`);
  });
}

function ensureGridLayer() {
  if (!map || map.getSource(GRID_SOURCE_ID)) return;
  map.addSource(GRID_SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });
  map.addLayer({
    id: GRID_FILL_LAYER_ID,
    type: 'fill',
    source: GRID_SOURCE_ID,
    paint: {
      'fill-color': '#9ecae1',
      'fill-opacity': GRID_FILL_OPACITY,
      'fill-antialias': false,
    },
  });
  map.on('click', GRID_FILL_LAYER_ID, (event) => {
    if (state.pointProbeActive) return;
    const feature = event.features?.[0];
    if (feature) selectGridCell(feature, event.lngLat);
  });
  map.on('mouseenter', GRID_FILL_LAYER_ID, () => { map.getCanvas().style.cursor = 'crosshair'; });
  map.on('mouseleave', GRID_FILL_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
}

function ensureReferenceOverlayLayer() {
  if (!map || map.getLayer(REFERENCE_OVERLAY_LAYER_ID)) return;
  map.addLayer({
    id: REFERENCE_OVERLAY_LAYER_ID,
    type: 'raster',
    source: 'osm',
    paint: {
      'raster-opacity': 0.28,
      'raster-saturation': -0.7,
      'raster-contrast': 0.3,
      'raster-brightness-min': 0.08,
      'raster-brightness-max': 0.96,
    },
  });
}

function ensureContourLayer() {
  if (!map || map.getSource(CONTOUR_SOURCE_ID)) return;
  map.addSource(CONTOUR_SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });
  map.addLayer({
    id: CONTOUR_LAYER_ID,
    type: 'line',
    source: CONTOUR_SOURCE_ID,
    paint: {
      'line-color': '#162231',
      'line-width': ['interpolate', ['linear'], ['zoom'], 2, 0.8, 6, 1.8],
      'line-opacity': 0.78,
    },
  });
  map.addLayer({
    id: CONTOUR_LABEL_LAYER_ID,
    type: 'symbol',
    source: CONTOUR_SOURCE_ID,
    layout: {
      'symbol-placement': 'line',
      'symbol-spacing': 180,
      'text-field': ['get', 'value_text'],
      'text-font': ['Open Sans Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 2, 10, 6, 12],
      'text-rotation-alignment': 'map',
      'text-pitch-alignment': 'viewport',
      'text-keep-upright': true,
      'text-allow-overlap': false,
      'text-ignore-placement': false,
    },
    paint: {
      'text-color': '#162231',
      'text-halo-color': '#f4f8fc',
      'text-halo-width': 1.3,
      'text-halo-blur': 0.35,
      'text-opacity': ['interpolate', ['linear'], ['zoom'], 2, 0.74, 6, 0.92],
    },
  });
  map.on('click', CONTOUR_LAYER_ID, (event) => {
    if (state.pointProbeActive) return;
    const feature = event.features?.[0];
    if (feature) selectContour(feature, event.lngLat);
  });
  map.on('mouseenter', CONTOUR_LAYER_ID, () => { map.getCanvas().style.cursor = 'crosshair'; });
  map.on('mouseleave', CONTOUR_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
}

function ensureFeatureLayers() {
  if (!map || map.getSource(FEATURE_SOURCE_ID)) return;

  map.addSource(FEATURE_SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });

  map.addLayer({
    id: FEATURE_LAYER_IDS.polygonFill,
    type: 'fill',
    source: FEATURE_SOURCE_ID,
    filter: ['==', ['geometry-type'], 'Polygon'],
    paint: {
      'fill-color': colorMatchExpression(),
      'fill-opacity': 0.2,
    },
  });

  map.addLayer({
    id: FEATURE_LAYER_IDS.polygonLine,
    type: 'line',
    source: FEATURE_SOURCE_ID,
    filter: ['==', ['geometry-type'], 'Polygon'],
    paint: {
      'line-color': colorMatchExpression(),
      'line-width': 2,
      'line-opacity': 0.95,
    },
  });

  map.addLayer({
    id: FEATURE_LAYER_IDS.line,
    type: 'line',
    source: FEATURE_SOURCE_ID,
    filter: ['==', ['geometry-type'], 'LineString'],
    paint: {
      'line-color': colorMatchExpression(),
      'line-width': 3,
      'line-opacity': 0.92,
    },
  });

  map.addLayer({
    id: FEATURE_LAYER_IDS.point,
    type: 'circle',
    source: FEATURE_SOURCE_ID,
    filter: ['==', ['geometry-type'], 'Point'],
    paint: {
      'circle-radius': 8,
      'circle-color': colorMatchExpression(),
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2,
    },
  });

  Object.values(FEATURE_LAYER_IDS).forEach((layerId) => {
    map.on('click', layerId, (event) => {
      if (state.pointProbeActive) return;
      const feature = event.features?.[0];
      if (feature) selectFeature(feature, event.lngLat);
    });
    map.on('mouseenter', layerId, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', layerId, () => { map.getCanvas().style.cursor = ''; });
  });
}

function fitCurrentBounds(options = {}) {
  if (!map) return;
  const [minLon, minLat, maxLon, maxLat] = state.currentBounds;
  map.fitBounds([[minLon, minLat], [maxLon, maxLat]], {
    padding: 28,
    maxZoom: 5.5,
    ...options,
  });
}

function renderChinesePlaceLabels() {
  placeMarkers.forEach((marker) => marker.remove());
  placeMarkers = [];
  chinesePlaceLabels.forEach(([label, lon, lat]) => {
    const el = document.createElement('span');
    el.className = 'base-place-label';
    el.textContent = label;
    placeMarkers.push(
      new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat([lon, lat])
        .addTo(map),
    );
  });
}

async function refreshRuns() {
  const runs = await api('/api/model-runs');
  state.runs = runs;
  const sel = $('runSelect');
  sel.innerHTML = '';
  if (!runs.length) {
    const o = document.createElement('option');
    o.value = 'ecmwf_demo';
    o.textContent = 'ecmwf_demo（待生成）';
    sel.appendChild(o);
  }
  runs.forEach((run) => {
    const o = document.createElement('option');
    o.value = run.run_id;
    o.textContent = `${run.run_id} (${run.model})`;
    sel.appendChild(o);
  });
  if (runs.find((r) => r.run_id === state.runId)) sel.value = state.runId;
  if (shouldUseNafpLayerSource()) syncForecastHoursFromPointRunTime();
  else await refreshForecastHours();
}

async function refreshForecastHours() {
  const runId = $('runSelect').value || state.runId;
  state.runId = runId;
  try {
    const fhs = await api(`/api/forecast-times?run_id=${encodeURIComponent(runId)}`);
    setForecastHourOptions(fhs);
  } catch (e) {
    setForecastHourOptions([0, 6, 12, 24, 36]);
  }
}

async function refreshLayers() {
  state.layers = await api('/api/layers');
  const sel = $('layerSelect');
  sel.innerHTML = '';
  Object.entries(state.layers).forEach(([id, cfg]) => {
    const o = document.createElement('option');
    o.value = id;
    o.textContent = cfg.title || id;
    sel.appendChild(o);
  });
  sel.value = state.layers.heavy_rain_score ? 'heavy_rain_score' : Object.keys(state.layers)[0] || '';
  renderLayerChips();
}

function paletteForLayer(layerId) {
  if (layerId.includes('risk') || layerId.includes('score')) return layerPalettes.score;
  if (layerId.includes('moisture')) return layerPalettes.moisture;
  if (layerId.includes('div') || layerId.includes('adv') || layerId.includes('vort') || layerId.includes('omega')) {
    return layerPalettes.diverging;
  }
  return layerPalettes.default;
}

function formatValue(value, unit = '') {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '无数据';
  const n = Number(value);
  const text = Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
  return unit ? `${text} ${unit}` : text;
}

function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toFixed(3);
}

function levelLabel(level) {
  return pointLevelNames[level] || level || '-';
}

function targetLabel(targetType) {
  return pointTargetNames[targetType] || targetType || '诊断目标';
}

function setPointProbeActive(active) {
  state.pointProbeActive = Boolean(active);
  const button = $('btnPointProbe');
  button.classList.toggle('active', state.pointProbeActive);
  button.setAttribute('aria-pressed', String(state.pointProbeActive));
  $('map').classList.toggle('point-probe-active', state.pointProbeActive);
  const context = selectedPointRunTime()
    ? `${selectedPointDataCode()} ${formatPointRunTimeLabel(selectedPointRunTime())}`
    : selectedPointDataCode();
  status(state.pointProbeActive ? `点位诊断已开启：${context}，点击地图任意位置查看评分和证据链` : '点位诊断已关闭');
}

function focusObjectDetailPanel() {
  const panel = document.querySelector('.analysis-panel');
  const detail = $('featureDetail');
  if (!panel || !detail || detail.hidden) return;
  requestAnimationFrame(() => {
    panel.scrollTo({
      top: Math.max(0, detail.offsetTop - 38),
      behavior: 'auto',
    });
  });
}

function showObjectDetail(title, text) {
  $('analysisTitle').hidden = false;
  $('analysisText').hidden = false;
  $('detailTitle').textContent = title;
  $('pointProbeBadge').hidden = true;
  document.querySelector('.analysis-panel')?.classList.remove('detail-focused');
  $('mapLegend')?.classList.remove('detail-shifted');
  const detail = $('featureDetail');
  detail.hidden = false;
  detail.className = 'object-detail-panel plain';
  detail.textContent = text;
  $('pointDiagnosisPanel').hidden = true;
  focusObjectDetailPanel();
}

function showObjectHtmlDetail(title, html) {
  $('analysisTitle').hidden = false;
  $('analysisText').hidden = false;
  $('detailTitle').textContent = title;
  $('pointProbeBadge').hidden = true;
  document.querySelector('.analysis-panel')?.classList.add('detail-focused');
  $('mapLegend')?.classList.add('detail-shifted');
  const detail = $('featureDetail');
  detail.hidden = false;
  detail.className = 'object-detail-panel';
  detail.innerHTML = html;
  $('pointDiagnosisPanel').hidden = true;
  focusObjectDetailPanel();
}

function showPointPanel(html) {
  $('analysisTitle').hidden = true;
  $('analysisText').hidden = true;
  $('detailTitle').textContent = '点位诊断';
  $('pointProbeBadge').hidden = false;
  document.querySelector('.analysis-panel')?.classList.remove('detail-focused');
  $('mapLegend')?.classList.remove('detail-shifted');
  $('featureDetail').hidden = true;
  const panel = $('pointDiagnosisPanel');
  panel.hidden = false;
  panel.innerHTML = html;
}

function renderPointProbeMarker(result) {
  if (pointProbeMarker) pointProbeMarker.remove();
  const requested = result.point?.requested || {};
  const el = document.createElement('div');
  el.className = 'point-probe-marker';
  el.innerHTML = '<span></span>';
  pointProbeMarker = new maplibregl.Marker({ element: el, anchor: 'center' })
    .setLngLat([requested.lon, requested.lat])
    .addTo(map);
}

function renderPointScoreCard(score) {
  const level = String(score.level || 'low');
  return `
    <article class="point-score-card ${escapeHtml(level)}">
      <span>${escapeHtml(targetLabel(score.target_type))}</span>
      <strong>${formatScore(score.score)}</strong>
      <em>${escapeHtml(levelLabel(level))}</em>
    </article>
  `;
}

function renderPointRiskCard(risk) {
  const level = String(risk.risk_level || risk.level || 'low');
  const hazardType = risk.hazard_type || risk.feature_type || risk.target_type || '';
  const label = risk.label || targetLabel(hazardType);
  return `
    <article class="point-risk-card ${escapeHtml(level)}">
      <header>
        <span>${escapeHtml(label)}</span>
        <strong>${formatScore(risk.score)}</strong>
      </header>
      <dl>
        <div><dt>风险等级</dt><dd>${escapeHtml(levelLabel(level))}</dd></div>
        <div><dt>风险类别</dt><dd>${escapeHtml(hazardType || '-')}</dd></div>
        <div><dt>风险域</dt><dd>${escapeHtml(risk.risk_domain || '-')}</dd></div>
      </dl>
    </article>
  `;
}

function riskDiagnosesByHazard(riskDiagnoses) {
  const byHazard = new Map();
  (riskDiagnoses || []).forEach((risk) => {
    const hazardType = risk.hazard_type || risk.feature_type || risk.target_type;
    if (!hazardType) return;
    const current = byHazard.get(hazardType);
    if (!current || Number(risk.score || 0) > Number(current.score || 0)) {
      byHazard.set(hazardType, risk);
    }
  });
  return byHazard;
}

function renderPointRiskChannelSection(channel, riskByHazard) {
  const cards = channel.hazards
    .map((hazardType) => riskByHazard.get(hazardType))
    .filter(Boolean)
    .map(renderPointRiskCard)
    .join('');
  if (!cards) return '';
  return `
    <section class="point-risk-channel" data-channel="${escapeHtml(channel.id)}">
      <header>
        <strong>${escapeHtml(channel.label)}</strong>
      </header>
      <div class="point-risk-channel-list">
        ${cards}
      </div>
    </section>
  `;
}

function evidenceSourceText(item) {
  if (item.source_path) return item.source_path;
  if (Array.isArray(item.source_paths)) return item.source_paths.join(' | ');
  return '';
}

function renderPointEvidenceItem(item) {
  const threshold = item.threshold === null || item.threshold === undefined ? '-' : formatValue(item.threshold, item.unit);
  const value = item.value || formatValue(item.raw_value, item.unit);
  const source = evidenceSourceText(item);
  return `
    <article class="point-evidence-item">
      <header>
        <strong>${escapeHtml(item.field || item.entry_id)}</strong>
        <span>${escapeHtml(item.signal || '')}</span>
      </header>
      <dl>
        <div><dt>点值</dt><dd>${escapeHtml(value)}</dd></div>
        <div><dt>阈值</dt><dd>${escapeHtml(threshold)}</dd></div>
        <div><dt>权重</dt><dd>${formatScore(item.weight)}</dd></div>
        <div><dt>贡献</dt><dd>${formatScore(item.contribution)}</dd></div>
      </dl>
      ${source ? `<p class="point-source-path">${escapeHtml(source)}</p>` : ''}
    </article>
  `;
}

function renderPointEvidenceChain(chain, index) {
  const open = index === 0 || Number(chain.score) >= 0.45;
  return `
    <details class="point-evidence-chain" ${open ? 'open' : ''}>
      <summary>
        <span>${escapeHtml(targetLabel(chain.target_type))}</span>
        <strong>${formatScore(chain.score)}</strong>
        <em>${escapeHtml(levelLabel(chain.level))}</em>
      </summary>
      <div class="point-evidence-list">
        ${(chain.evidence || []).map(renderPointEvidenceItem).join('')}
      </div>
    </details>
  `;
}

function renderPointDiagnosis(result) {
  const point = result.point || {};
  const requested = point.requested || {};
  const nearest = point.nearest_grid_point || {};
  const conclusions = result.diagnosis_conclusions || [];
  const chains = result.evidence_chains || [];
  const riskDiagnoses = result.risk_diagnoses || [];
  const riskByHazard = riskDiagnosesByHazard(riskDiagnoses);
  const riskChannelHtml = pointRiskChannels
    .map((channel) => renderPointRiskChannelSection(channel, riskByHazard))
    .join('');
  showPointPanel(`
    <div class="point-summary-strip">
      <div>
        <span>点击点</span>
        <strong>${formatValue(requested.lat)} / ${formatValue(requested.lon)}</strong>
      </div>
      <div>
        <span>最近格点</span>
        <strong>${formatValue(nearest.lat)} / ${formatValue(nearest.lon)}</strong>
      </div>
      <div>
        <span>格点距离</span>
        <strong>${formatValue(nearest.distance_degrees, 'deg')}</strong>
      </div>
    </div>
    ${riskChannelHtml ? `
      <section class="point-risk-grid">
        ${riskChannelHtml}
      </section>
    ` : ''}
    <div class="point-score-grid">
      ${(result.scores || []).map(renderPointScoreCard).join('')}
    </div>
    <section class="point-chain-stack">
      ${chains.map(renderPointEvidenceChain).join('')}
    </section>
    ${conclusions.length ? `
      <section class="point-conclusions">
        ${conclusions.map((item) => `<p>${escapeHtml(item.headline || item.action_hint || '')}</p>`).join('')}
      </section>
    ` : ''}
  `);
  renderPointProbeMarker(result);
  status(`点位诊断完成：${formatValue(requested.lat)} / ${formatValue(requested.lon)}`);
}

async function diagnosePointAt(lngLat) {
  const runTime = selectedPointRunTime();
  if (!runTime) {
    showPointPanel(`
      <div class="point-loading error">
        <strong>点位诊断未就绪</strong>
        <span>未发现可用起报时次，请检查数据编码目录配置。</span>
      </div>
    `);
    status('点位诊断未就绪：未发现可用起报时次');
    return;
  }
  const payload = {
    data_code: selectedPointDataCode(),
    run_time: selectedPointRunTime(),
    forecast_hour: Number($('fhSelect').value || state.forecastHour),
    lat: Number(lngLat.lat.toFixed(6)),
    lon: Number(lngLat.lng.toFixed(6)),
  };
  showPointPanel(`
    <div class="point-loading">
      <strong>点位诊断计算中</strong>
      <span>${escapeHtml(payload.data_code)} · ${escapeHtml(formatPointRunTimeLabel(payload.run_time))} · ${formatValue(payload.lat)} / ${formatValue(payload.lon)} · +${payload.forecast_hour}h</span>
    </div>
  `);
  status(`点位诊断计算中：${payload.lat.toFixed(2)} / ${payload.lon.toFixed(2)}`);
  try {
    const result = await postEnvelope('/api/v1/diagnosis/nafp/point', payload);
    renderPointDiagnosis(result);
    const best = result.scores?.[0];
    popup
      .setLngLat([payload.lon, payload.lat])
      .setHTML(`<strong>点位诊断</strong><span>${targetLabel(best?.target_type)} ${formatScore(best?.score)}</span>`)
      .addTo(map);
  } catch (error) {
    showPointPanel(`
      <div class="point-loading error">
        <strong>点位诊断失败</strong>
        <span>${escapeHtml(error.message)}</span>
      </div>
    `);
    status(`点位诊断失败：${error.message}`);
  }
}

function updateLegend(metadata, palette) {
  $('legendTitle').textContent = metadata.title || metadata.layer_id || '诊断图层';
  $('legendMin').textContent = `低值 ${formatValue(metadata.min, metadata.unit)}`;
  $('legendMax').textContent = `高值 ${formatValue(metadata.max, metadata.unit)}`;
  $('legendRamp').style.background = `linear-gradient(90deg, ${palette.join(', ')})`;
  $('mapLegend').hidden = false;
}

async function loadLayer(options = {}) {
  if (!map || !state.mapReady) return;
  const layer = $('layerSelect').value;
  const fh = Number($('fhSelect').value);
  if (!layer || Number.isNaN(fh)) return;
  state.forecastHour = fh;
  if (shouldUseNafpLayerSource()) {
    await loadNafpLayerData(layer, fh, options);
    return;
  }

  const runId = $('runSelect').value;
  if (!runId) return;

  state.runId = runId;
  const title = state.layers[layer]?.title || layer;
  status(`正在加载 GIS 图层：${title} +${fh}h`);

  const md = await api(`/api/layers/${layer}/metadata?run_id=${encodeURIComponent(runId)}&forecast_hour=${fh}`);
  state.currentBounds = metadataToBounds(md);
  const grid = await api(buildLayerGridUrl(layer, runId, fh, Date.now()));
  const source = map.getSource(GRID_SOURCE_ID);
  source.setData(grid);
  const palette = paletteForLayer(layer);
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(md.min, md.max, palette));
  await loadContours();
  updateLegend(md, palette);
  renderLayerChips();
  if (options.fitBounds !== false) fitCurrentBounds({ duration: 450 });
  status(`已加载 GIS 图层：${md.title || layer} +${fh}h`);
  await loadAnalysis();
}

async function loadNafpLayerData(layer, fh) {
  const options = arguments[2] || {};
  if (!selectedPointRunTime()) {
    status(`NAFP 原始格点未就绪：${selectedPointDataCode()} 未发现起报时次`);
    return;
  }
  const title = state.layers[layer]?.title || layer;
  status(`正在加载 NAFP 原始格点：${title} ${formatPointRunTimeLabel(selectedPointRunTime())} +${fh}h`);

  const md = await getEnvelope(buildNafpLayerMetadataUrl(layer, selectedPointDataCode(), selectedPointRunTime(), fh, Date.now()));
  state.currentBounds = metadataToBounds(md);
  const grid = await getEnvelope(buildNafpLayerGridUrl(layer, selectedPointDataCode(), selectedPointRunTime(), fh, Date.now()));
  const source = map.getSource(GRID_SOURCE_ID);
  source.setData(grid);
  const palette = paletteForLayer(layer);
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(md.min, md.max, palette));
  await loadContours();
  updateLegend(md, palette);
  renderLayerChips();
  if (options.fitBounds !== false) fitCurrentBounds({ duration: 450 });
  status(`已加载 NAFP 原始格点：${md.title || layer} +${fh}h`);
}

function clearContours() {
  const source = map?.getSource(CONTOUR_SOURCE_ID);
  if (source) source.setData({ type: 'FeatureCollection', features: [] });
}

async function loadContours() {
  if (!map || !state.mapReady) return;
  if (!$('contourToggle')?.checked) {
    clearContours();
    return;
  }
  const layer = $('layerSelect').value;
  const fh = Number($('fhSelect').value);
  const useNafp = shouldUseNafpLayerSource();
  const runId = $('runSelect').value;
  if (!layer || Number.isNaN(fh)) {
    clearContours();
    return;
  }
  if (useNafp && !selectedPointRunTime()) {
    clearContours();
    return;
  }
  if (!useNafp && !runId) {
    clearContours();
    return;
  }
  try {
    const contours = useNafp
      ? await getEnvelope(buildNafpLayerContourUrl(layer, selectedPointDataCode(), selectedPointRunTime(), fh, Date.now()))
      : await api(buildLayerContourUrl(layer, runId, fh, Date.now()));
    map.getSource(CONTOUR_SOURCE_ID).setData(contours);
  } catch (error) {
    console.warn(`contour load failed: ${layer}`, error);
    clearContours();
  }
}

function selectGridCell(feature, lngLat) {
  const props = feature.properties || {};
  const title = props.title || '诊断图层';
  const value = formatValue(props.value, props.unit);
  showObjectDetail('格点详情', [
    `图层：${title}`,
    `格点值：${value}`,
    `行列：${props.row}, ${props.col}`,
  ].join('\n'));
  popup
    .setLngLat(lngLat)
    .setHTML(`<strong>${title}</strong><span>格点值 ${value}</span>`)
    .addTo(map);
}

function selectContour(feature, lngLat) {
  const props = feature.properties || {};
  const title = props.title || '等值线';
  const value = formatValue(props.value, props.unit);
  showObjectDetail('等值线详情', [
    `图层：${title}`,
    `等值线：${value}`,
  ].join('\n'));
  popup
    .setLngLat(lngLat)
    .setHTML(`<strong>${title}</strong><span>等值线 ${value}</span>`)
    .addTo(map);
}

function selectFeature(feature, lngLat) {
  const props = feature.properties || {};
  state.selectedFeatureId = props.id || featureRowId(feature);
  renderFeatureIndex();
  showObjectHtmlDetail('对象详情', renderFeatureDetailCard(props));
  void syncLayerForFeature(props);
  const name = featureTypeNames[props.feature_type] || props.feature_type || '天气系统';
  const title = `${name} ${featureDisplayLabel(props)}`;
  const confidence = props.confidence === undefined ? '' : `<span>置信度 ${Number(props.confidence).toFixed(2)}</span>`;
  popup
    .setLngLat(lngLat)
    .setHTML(`<strong>${title}</strong>${confidence}`)
    .addTo(map);
}

function parseFeatureProperty(value) {
  if (typeof value !== 'string') return value;
  const text = value.trim();
  if (!text.startsWith('{') && !text.startsWith('[')) return value;
  try {
    return JSON.parse(text);
  } catch (error) {
    return value;
  }
}

function featureEvidenceLine(item) {
  if (typeof item === 'string') return item;
  if (!item || typeof item !== 'object') return String(item ?? '');
  const label = item.signal || item.entry_id || item.field || '证据';
  const value = item.value || formatValue(item.raw_value, item.unit);
  const threshold = item.threshold === null || item.threshold === undefined
    ? ''
    : `阈值 ${formatValue(item.threshold, item.unit)}`;
  const source = item.source_path || (Array.isArray(item.source_paths) ? item.source_paths[0] : '');
  return [label, value, threshold, source].filter(Boolean).join(' | ');
}

function featureEvidenceStrengthText(item) {
  const contribution = Number(item?.contribution);
  if (Number.isFinite(contribution)) return contribution.toFixed(3);
  const normalized = Number(item?.normalized_score);
  const weight = Number(item?.weight);
  if (Number.isFinite(normalized) && Number.isFinite(weight)) return (normalized * weight).toFixed(3);
  if (Number.isFinite(normalized)) return normalized.toFixed(3);
  return '-';
}

function featureMetric(label, value) {
  return `
    <div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function featureEvidenceItem(item) {
  if (typeof item === 'string') {
    return `
      <li class="feature-evidence-item">
        <header><strong>${escapeHtml(item)}</strong><span>文本证据</span></header>
      </li>
    `;
  }
  const label = item?.signal || item?.entry_id || item?.field || '证据';
  const source = item?.source_path || (Array.isArray(item?.source_paths) ? item.source_paths[0] : '');
  return `
    <li class="feature-evidence-item">
      <header>
        <strong>${escapeHtml(label)}</strong>
        <span>贡献 ${escapeHtml(featureEvidenceStrengthText(item))}</span>
      </header>
      <dl>
        <div><dt>字段</dt><dd>${escapeHtml(item?.field || '-')}</dd></div>
        <div><dt>值</dt><dd>${escapeHtml(item?.value || formatValue(item?.raw_value, item?.unit))}</dd></div>
        <div><dt>阈值</dt><dd>${escapeHtml(item?.threshold === null || item?.threshold === undefined ? '-' : formatValue(item.threshold, item?.unit))}</dd></div>
        <div><dt>规则</dt><dd>${escapeHtml(item?.entry_id || '-')}</dd></div>
      </dl>
      ${source ? `<p class="feature-source-path">${escapeHtml(source)}</p>` : ''}
    </li>
  `;
}

function renderFeatureDetailCard(props) {
  const name = featureTypeNames[props.feature_type] || props.feature_type || '天气系统';
  const quality = featureQuality(props);
  const layerSuggestion = recommendedFeatureLayer(props, Object.keys(state.layers));
  const evidence = parseFeatureProperty(props.evidence);
  const rankedEvidence = rankFeatureEvidence(evidence);
  const missingEvidence = parseFeatureProperty(props.missing_evidence);
  const bbox = parseFeatureProperty(props.bbox);
  const bboxText = Array.isArray(bbox) && bbox.length === 4
    ? `${formatValue(bbox[0])}, ${formatValue(bbox[1])} → ${formatValue(bbox[2])}, ${formatValue(bbox[3])}`
    : '-';
  const evidenceCount = Array.isArray(evidence) ? evidence.length : 0;
  const missingCount = Array.isArray(missingEvidence) ? missingEvidence.length : 0;
  return `
    <section class="object-detail-card">
      <header class="object-detail-head">
        <div>
          <span>天气系统对象</span>
          <strong>${escapeHtml(name)}</strong>
        </div>
        <em class="object-quality-badge ${escapeHtml(quality.level)}">${escapeHtml(quality.label)}</em>
      </header>
      <div class="object-quality-strip ${escapeHtml(quality.level)}">
        ${featureMetric('置信度', quality.scoreText)}
        ${featureMetric('证据数', String(evidenceCount))}
        ${featureMetric('缺测项', String(missingCount))}
      </div>
      ${props.diagnosis ? `<p class="object-diagnosis">${escapeHtml(props.diagnosis)}</p>` : ''}
      <dl class="object-meta-grid">
        <div><dt>编号</dt><dd>${escapeHtml(props.id || '-')}</dd></div>
        <div><dt>层次</dt><dd>${escapeHtml(props.level || '-')}</dd></div>
        <div><dt>评分</dt><dd>${escapeHtml(props.score !== undefined ? formatValue(props.score) : '-')}</dd></div>
        <div><dt>范围</dt><dd>${escapeHtml(bboxText)}</dd></div>
        <div><dt>联动图层</dt><dd>${escapeHtml(layerSuggestion ? layerDisplayName(layerSuggestion.layerId) : '-')}</dd></div>
      </dl>
    </section>
    <section class="feature-evidence-card">
      <header>
        <strong>证据链</strong>
        <span>按贡献排序</span>
      </header>
      <ol class="feature-evidence-list">
        ${rankedEvidence.length ? rankedEvidence.map(featureEvidenceItem).join('') : '<li class="feature-evidence-empty">暂无结构化证据。</li>'}
      </ol>
    </section>
  `;
}

function formatFeatureDetail(props) {
  const name = featureTypeNames[props.feature_type] || props.feature_type || '天气系统';
  const lines = [
    `类型：${name}`,
    props.id ? `编号：${props.id}` : null,
    props.level ? `层次：${props.level}` : null,
    props.value !== undefined ? `数值：${formatValue(props.value, props.unit)}` : null,
    props.confidence !== undefined ? `置信度：${Number(props.confidence).toFixed(2)}` : null,
  ].filter(Boolean);
  const evidence = parseFeatureProperty(props.evidence);
  if (Array.isArray(evidence) && evidence.length) {
    lines.push('证据：');
    evidence.forEach((item) => lines.push(`- ${featureEvidenceLine(item)}`));
  }
  return lines.join('\n');
}

function clearPointMarkers() {
  pointMarkers.forEach((marker) => marker.remove());
  pointMarkers = [];
}

function clearPointProbeMarker() {
  if (pointProbeMarker) pointProbeMarker.remove();
  pointProbeMarker = null;
}

function featureToggleInputs(selector = 'input') {
  return [...document.querySelectorAll(`#featureToggles ${selector}, #riskFeatureToggles ${selector}`)];
}

function selectedFeatureTypes() {
  return [...document.querySelectorAll('#featureToggles input:checked, #riskFeatureToggles input:checked')]
    .map((input) => input.value);
}

function clearWeatherFeatures(message = '未选择风险或天气系统，仅显示地图') {
  state.features = [];
  state.selectedFeatureId = '';
  const featureSource = map?.getSource(FEATURE_SOURCE_ID);
  if (featureSource) featureSource.setData({ type: 'FeatureCollection', features: [] });
  clearPointMarkers();
  if (popup) popup.remove();
  showObjectDetail('对象详情', '未选择风险或天气系统。');
  renderFeatureIndex();
  status(message);
}

function clearFeatureSelection() {
  featureToggleInputs().forEach((input) => {
    input.checked = false;
  });
  clearWeatherFeatures();
}

function clearMapOverlays() {
  $('layerSelect').value = '';
  renderLayerChips();
  const gridSource = map?.getSource(GRID_SOURCE_ID);
  if (gridSource) gridSource.setData({ type: 'FeatureCollection', features: [] });
  clearContours();
  clearPointProbeMarker();
  $('mapLegend').hidden = true;
  featureToggleInputs().forEach((input) => {
    input.checked = false;
  });
  clearWeatherFeatures('未选择要素，仅显示地图');
  $('analysisText').textContent = '未选择要素。';
}

function renderPointMarkers(features) {
  clearPointMarkers();
  features
    .filter((feature) => feature.geometry?.type === 'Point')
    .forEach((feature) => {
      const props = feature.properties || {};
      const [lon, lat] = feature.geometry.coordinates;
      const color = featureColors[props.feature_type] || '#333333';
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'weather-point-label';
      el.textContent = featureDisplayLabel(props);
      el.style.color = color;
      el.style.borderColor = color;
      el.addEventListener('click', (event) => {
        event.stopPropagation();
        if (state.pointProbeActive) {
          diagnosePointAt({ lng: lon, lat });
          return;
        }
        selectFeature(feature, [lon, lat]);
      });
      pointMarkers.push(
        new maplibregl.Marker({ element: el, anchor: 'left', offset: [12, 0] })
          .setLngLat([lon, lat])
          .addTo(map),
      );
    });
}

async function loadNafpFeatures(selected, fh) {
  if (!selectedPointRunTime()) {
    clearWeatherFeatures(`NAFP 对象未就绪：${selectedPointDataCode()} 未发现起报时次`);
    return;
  }
  status(`正在加载 ${selected.length} 类 NAFP 风险/天气系统对象...`);
  try {
    const fc = await getEnvelope(buildNafpFeaturesUrl(selected, selectedPointDataCode(), selectedPointRunTime(), fh, Date.now()));
    state.features = fc.features || [];
    state.selectedFeatureId = '';
    map.getSource(FEATURE_SOURCE_ID).setData(fc);
    renderPointMarkers(state.features);
    renderFeatureIndex();
    if (fc.properties?.summary) $('analysisText').textContent = fc.properties.summary;
    status(`已加载 ${state.features.length} 个 NAFP 风险/天气系统对象`);
  } catch (error) {
    console.warn('NAFP feature load failed', error);
    state.features = [];
    state.selectedFeatureId = '';
    map.getSource(FEATURE_SOURCE_ID).setData({ type: 'FeatureCollection', features: [] });
    clearPointMarkers();
    renderFeatureIndex();
    status(`NAFP 风险/天气系统加载失败：${error.message}`);
  }
}

async function loadFeatures() {
  if (!map || !state.mapReady) return;
  const runId = $('runSelect').value;
  const fh = Number($('fhSelect').value);
  const selected = selectedFeatureTypes();
  if (!selected.length) {
    clearWeatherFeatures();
    return;
  }
  if (shouldUseNafpLayerSource()) {
    await loadNafpFeatures(selected, fh);
    return;
  }
  status(`正在加载 ${selected.length} 类风险/天气系统对象...`);

  const responses = await Promise.all(selected.map(async (type) => {
    try {
      return await api(`/api/features?run_id=${encodeURIComponent(runId)}&forecast_hour=${fh}&type=${type}`);
    } catch (e) {
      console.warn(`feature load failed: ${type}`, e);
      return null;
    }
  }));

  const fc = mergeFeatureCollections(responses);
  state.features = fc.features;
  state.selectedFeatureId = '';
  map.getSource(FEATURE_SOURCE_ID).setData(fc);
  renderPointMarkers(state.features);
  renderFeatureIndex();
  status(`已加载 ${state.features.length} 个风险/天气系统对象`);
}

async function handleFeatureToggleChange(event) {
  if (!event.target.matches('#featureToggles input[type="checkbox"], #riskFeatureToggles input[type="checkbox"]')) return;
  await loadFeatures();
}

async function loadAnalysis() {
  const runId = $('runSelect').value;
  const fh = Number($('fhSelect').value);
  try {
    const a = await api(`/api/analysis/situation?run_id=${encodeURIComponent(runId)}&forecast_hour=${fh}`);
    $('analysisText').textContent = a.detail || a.summary || JSON.stringify(a, null, 2);
  } catch (e) {
    $('analysisText').textContent = `暂无分析结果：${e.message}`;
  }
}

async function generateDemo() {
  status('正在生成示例数据...');
  await api('/api/jobs/generate-demo', { method: 'POST' });
  status('示例数据已生成，请运行诊断');
}

async function runDiagnose() {
  status('诊断计算中，请稍候...');
  await api('/api/jobs/diagnose?model=ecmwf&file_path=data/raw/ecmwf_demo.nc&run_id=ecmwf_demo', { method: 'POST' });
  status('诊断完成');
  await refreshRuns();
  await loadLayer();
  await loadFeatures();
}

function wireEvents() {
  $('btnDemo').addEventListener('click', generateDemo);
  $('btnDiagnose').addEventListener('click', runDiagnose);
  $('btnPointProbe').addEventListener('click', () => {
    setPointProbeActive(!state.pointProbeActive);
  });
  $('btnLoadLayer').addEventListener('click', loadLayer);
  $('btnLoadFeatures').addEventListener('click', loadFeatures);
  $('featureToggles').addEventListener('change', handleFeatureToggleChange);
  $('riskFeatureToggles').addEventListener('change', handleFeatureToggleChange);
  $('btnClearOverlays').addEventListener('click', clearMapOverlays);
  $('btnClearFeatures').addEventListener('click', clearFeatureSelection);
  $('featureIndexTypeFilter').addEventListener('change', renderFeatureIndex);
  $('featureIndexQualityFilter').addEventListener('change', renderFeatureIndex);
  $('layerSourceSelect').addEventListener('change', async () => {
    state.layerSource = selectedLayerSource();
    syncProductRunVisibility();
    if (shouldUseNafpLayerSource()) syncForecastHoursFromPointRunTime();
    else await refreshForecastHours();
    await loadLayer();
    await loadFeatures();
  });
  $('pointDataCodeSelect').addEventListener('change', async () => {
    await refreshPointRunTimes();
    if (shouldUseNafpLayerSource()) {
      syncForecastHoursFromPointRunTime();
      await loadLayer();
    }
  });
  $('pointRunTimeSelect').addEventListener('change', async () => {
    state.pointRunTime = selectedPointRunTime();
    if (shouldUseNafpLayerSource()) {
      syncForecastHoursFromPointRunTime();
      await loadLayer();
    }
  });
  $('runSelect').addEventListener('change', async () => {
    if (shouldUseNafpLayerSource()) state.runId = $('runSelect').value;
    else await refreshForecastHours();
    await loadLayer();
    await loadFeatures();
  });
  $('fhSelect').addEventListener('change', () => setForecastHour(Number($('fhSelect').value)));
  $('contourToggle').addEventListener('change', loadContours);
  $('btnStepPrev').addEventListener('click', () => {
    setForecastHour(nextForecastHour(state.forecastHours, state.forecastHour, -1));
  });
  $('btnStepNext').addEventListener('click', () => {
    setForecastHour(nextForecastHour(state.forecastHours, state.forecastHour, 1));
  });
}

async function init() {
  setupFeatureToggles();
  setupFeatureIndexControls();
  wireEvents();
  syncProductRunVisibility();
  initializeMap();
  await refreshLayers();
  await refreshPointDataSources();
  await refreshRuns();

  if (map) {
    const loadInitialMapData = async () => {
      await loadLayer();
      await loadFeatures();
    };
    if (state.mapReady) await loadInitialMapData();
    else map.once('load', loadInitialMapData);
  }
}

init().catch((e) => {
  console.error(e);
  status(`初始化失败：${e.message}`);
});
