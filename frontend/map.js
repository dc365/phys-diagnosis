const DEFAULT_BOUNDS = [70, 15, 140, 55];
const DEFAULT_CENTER = [105, 35];
const DEFAULT_POINT_DATA_CODE = 'NAFP_ECTHIN_NC';
const GRID_SOURCE_ID = 'diagnostic-grid';
const GRID_FILL_LAYER_ID = 'diagnostic-grid-fill';
const REFERENCE_OVERLAY_LAYER_ID = 'map-reference-overlay';
const GRID_FILL_OPACITY = 0.5;
const SOUNDING_GRID_FILL_OPACITY = 0.18;
const CONTOUR_SOURCE_ID = 'diagnostic-contours';
const CONTOUR_LAYER_ID = 'diagnostic-contour-lines';
const CONTOUR_LABEL_SOURCE_ID = 'diagnostic-contour-label-points';
const CONTOUR_LABEL_LAYER_ID = 'diagnostic-contour-labels';
const Z500_CONTOUR_COLOR = '#3155d4';
const MAX_CONTOUR_LABELS = 36;
const CONTOUR_LABEL_BOUNDS_PADDING_DEGREES = 1.5;
const CONTOUR_LABEL_MIN_DISTANCE_DEGREES = 2.4;
const CONTOUR_LABEL_SAME_VALUE_MIN_DISTANCE_DEGREES = 6.4;
const FEATURE_SOURCE_ID = 'weather-features';
const FEATURE_LAYER_IDS = {
  polygonFill: 'weather-feature-polygons',
  polygonLine: 'weather-feature-polygon-outlines',
  line: 'weather-feature-lines',
  point: 'weather-feature-points',
};
const AREA_RISK_SOURCE_ID = 'area-risk';
const AREA_RISK_BBOX_SOURCE_ID = 'area-risk-selected-bbox';
const AREA_RISK_LAYER_IDS = {
  halo: 'area-risk-halo',
  point: 'area-risk-points',
  selectedBbox: 'area-risk-selected-bbox',
};
const AREA_RISK_API_PATH = '/api/v1/diagnosis/nafp/area-risks';
const DEFAULT_SOUNDING_CSV_PATH = 'test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625/regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv';
const SOUNDING_DEFAULT_TYPES = [
  'high',
  'low',
  'warm_center',
  'cold_center',
  'trough',
  'ridge',
  'short_duration_heavy_rain_risk',
  'rotating_storm_risk',
  'severe_convection_composite_risk',
];
const BASEMAP_SOURCE_ID = 'base-map-raster';
const BASEMAP_LABEL_SOURCE_ID = 'base-map-label-raster';
const BASEMAP_LAYER_ID = 'base-map-raster';
const BASEMAP_LABEL_LAYER_ID = 'base-map-label-raster';
const BASEMAP_LOCAL_TEMPLATE = '/static/basemaps/china/{z}/{x}/{y}.png';
const BASEMAP_IDS = new Set(['offline', 'local-xyz', 'tdt-vector', 'tdt-image']);
const LOCAL_TEST_FORECAST_HOURS = [0, 24];
const LOCAL_TEST_RUN_TIMES = [
  { run_time: '2026-06-17T20:00:00', forecast_hours: LOCAL_TEST_FORECAST_HOURS },
  { run_time: '2026-06-17T08:00:00', forecast_hours: LOCAL_TEST_FORECAST_HOURS },
];

const state = {
  runs: [],
  runId: 'ecmwf_demo',
  forecastHour: 24,
  forecastHours: [],
  dataCategory: 'forecast',
  layerSource: 'nafp',
  layers: {},
  contours: null,
  currentBounds: DEFAULT_BOUNDS,
  features: [],
  selectedFeatureId: '',
  mapReady: false,
  pointProbeActive: false,
  pointDataSources: [],
  pointDataCode: DEFAULT_POINT_DATA_CODE,
  pointRunTime: '',
  pointRunTimes: [],
  nafpPrecomputeKey: '',
  nafpPrecomputePromise: null,
  areaRiskCatalog: null,
  areaRiskFeatures: [],
  selectedAreaRiskId: '',
  areaRiskLoaded: false,
  featureLoadToken: 0,
  basemap: 'offline',
};

const weatherSystemFeatureTypes = [
  ['high', '高压中心'], ['low', '低压中心'], ['subtropical_high', '副高588区'],
  ['trough', '槽线候选'], ['ridge', '脊线候选'], ['low_level_convergence', '低层辐合区'],
  ['upper_divergence', '高空辐散区'], ['low_level_jet', '低空急流'],
  ['moisture_transport', '水汽输送带'], ['front_candidate', '锋面轴线'],
  ['shear_line', '切变线'], ['front_with_shear', '锋区切变线'],
  ['low_level_convergence_axis', '低层辐合轴'], ['upper_divergence_axis', '高空辐散轴'],
  ['cold_vortex', '冷涡候选'], ['mid_level_vortex', '低涡候选'],
  ['upper_jet', '高空急流'], ['upper_jet_exit_region', '急流出口辐散区'],
  ['pv_anomaly', '高空PV异常'], ['surface_front_candidate', '地面锋区候选'],
  ['dryline_candidate', '干线候选'],
];

const riskFeatureTypes = [
  ['persistent_heavy_rain_risk', '持续性强降水'],
  ['short_duration_heavy_rain_risk', '短时强降水'],
  ['thunderstorm_gale_risk', '雷暴大风/下击暴流'],
  ['hail_risk', '冰雹'],
  ['rotating_storm_risk', '旋转风暴/超级单体潜势'],
  ['severe_convection_composite_risk', '强对流综合风险'],
];

const featureTypes = [...weatherSystemFeatureTypes, ...riskFeatureTypes];

const areaRiskTypes = [
  ['persistent_heavy_rain', '持续性强降水'],
  ['short_duration_heavy_rain', '短时强降水'],
  ['thunderstorm_gale', '雷暴大风/下击暴流'],
  ['hail', '冰雹'],
  ['rotating_storm_or_supercell', '旋转风暴/超级单体潜势'],
  ['severe_convection_composite', '强对流综合风险'],
];

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
  shear_line: '#2f9e44',
  front_with_shear: '#7950f2',
  low_level_convergence_axis: '#087f5b',
  upper_divergence_axis: '#1098ad',
  cold_vortex: '#364fc7',
  mid_level_vortex: '#1971c2',
  upper_jet: '#c2255c',
  upper_jet_exit_region: '#e64980',
  pv_anomaly: '#6741d9',
  surface_front_candidate: '#f03e3e',
  dryline_candidate: '#a16207',
  warm_center: '#e03131',
  cold_center: '#364fc7',
  persistent_heavy_rain_risk: '#b02a37',
  short_duration_heavy_rain_risk: '#1971c2',
  thunderstorm_gale_risk: '#5f3dc4',
  hail_risk: '#0b7285',
  rotating_storm_risk: '#e67700',
  severe_convection_composite_risk: '#862e9c',
};

const frontTypeColors = {
  cold_front: '#1864ab',
  warm_front: '#e03131',
  stationary_front: '#7048e8',
  mixed_front: '#5c677d',
  front_candidate: featureColors.front_candidate,
};

const areaRiskColors = {
  persistent_heavy_rain: featureColors.persistent_heavy_rain_risk,
  short_duration_heavy_rain: featureColors.short_duration_heavy_rain_risk,
  thunderstorm_gale: featureColors.thunderstorm_gale_risk,
  hail: featureColors.hail_risk,
  rotating_storm_or_supercell: featureColors.rotating_storm_risk,
  severe_convection_composite: featureColors.severe_convection_composite_risk,
};

const featureLegendKinds = {
  high: 'point',
  low: 'point',
  trough: 'line',
  ridge: 'line',
  low_level_jet: 'line',
  moisture_transport: 'line',
  front_candidate: 'line',
  shear_line: 'line',
  front_with_shear: 'line',
  low_level_convergence_axis: 'line',
  upper_divergence_axis: 'line',
  cold_vortex: 'point',
  mid_level_vortex: 'point',
  warm_center: 'point',
  cold_center: 'point',
  upper_jet: 'line',
  surface_front_candidate: 'line',
  dryline_candidate: 'line',
};

const featureTypeNames = {
  ...Object.fromEntries(featureTypes),
  warm_center: '暖中心',
  cold_center: '冷中心',
};
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
const pointRiskHazardTypes = new Set(pointRiskChannels.flatMap((channel) => channel.hazards));
const pointRiskTargetAliases = new Map([
  ['persistent_heavy_rain_risk', 'persistent_heavy_rain'],
  ['short_duration_heavy_rain_risk', 'short_duration_heavy_rain'],
  ['thunderstorm_gale_risk', 'thunderstorm_gale'],
  ['hail_risk', 'hail'],
  ['rotating_storm_risk', 'rotating_storm_or_supercell'],
  ['rotating_storm_or_supercell_risk', 'rotating_storm_or_supercell'],
]);

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
  areaRiskPayloadToFeatureCollection,
  areaRiskValidTime,
  buildLayerContourUrl,
  buildColorRampExpression,
  colorRampDomainForLayer,
  buildLayerGridUrl,
  buildNafpAreaRiskUrl,
  buildNafpFeaturesUrl,
  buildSoundingFeaturesUrl,
  buildSoundingLayerContourUrl,
  buildSoundingLayerGridUrl,
  buildSoundingLayerMetadataUrl,
  buildNafpLayerContourUrl,
  buildNafpLayerGridUrl,
  buildNafpLayerMetadataUrl,
  featureDisplayLabel,
  featureGeometryBounds,
  featureIndexRows,
  featureQuality,
  forecastHourLabel,
  legendEndpointLabel,
  mergeFeatureCollections,
  metadataToBounds,
  nextForecastHour,
  pickDefaultRunTime,
  primaryFeatureCollection,
  rankFeatureEvidence,
  recommendedFeatureLayer,
  runTimesWithDefaultRunTime,
  smoothFeatureCollectionForDisplay,
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

function dataSourceLabel(item) {
  return item?.label || item?.display_name || item?.mode_name || item?.name || item?.code || DEFAULT_POINT_DATA_CODE;
}

function colorMatchExpression() {
  const expression = ['case', ['==', ['get', 'feature_type'], 'front_candidate'], frontTypeColorExpression()];
  const featureTypeExpression = ['match', ['get', 'feature_type']];
  Object.entries(featureColors).forEach(([type, color]) => featureTypeExpression.push(type, color));
  featureTypeExpression.push('#333333');
  expression.push(featureTypeExpression);
  return expression;
}

function frontTypeColorExpression() {
  const expression = ['match', ['get', 'front_type']];
  Object.entries(frontTypeColors).forEach(([type, color]) => expression.push(type, color));
  expression.push(frontTypeColors.front_candidate);
  return expression;
}

function featureColor(properties) {
  const props = typeof properties === 'string' ? { feature_type: properties } : (properties || {});
  if (props.feature_type === 'front_candidate') {
    return frontTypeColors[props.front_type] || featureColors.front_candidate;
  }
  return featureColors[props.feature_type] || '#333333';
}

function areaRiskColorExpression() {
  const expression = ['match', ['get', 'hazard_type']];
  Object.entries(areaRiskColors).forEach(([type, color]) => expression.push(type, color));
  expression.push('#32d5e7');
  return expression;
}

function contourColorExpression() {
  return ['match', ['get', 'layer_id'], 'z500', Z500_CONTOUR_COLOR, '#162231'];
}

function featureLegendKind(type) {
  return featureLegendKinds[type] || 'area';
}

function isRiskLayer(layerId) {
  return String(layerId || '').startsWith('risk_');
}

function isElementLayer(layerId) {
  return !isRiskLayer(layerId);
}

function createBaseStyle() {
  return {
    version: 8,
    glyphs: '/static/vendor/maplibre-fonts/{fontstack}/{range}.pbf',
    sources: {},
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: { 'background-color': '#edf4fb' },
      },
    ],
  };
}

function mapPageParams() {
  return new URLSearchParams(window.location.search || '');
}

function mapConfig() {
  return window.WEATHER_MAP_CONFIG || {};
}

function normalizedBasemapId(value) {
  const id = String(value || '').trim();
  return BASEMAP_IDS.has(id) ? id : 'offline';
}

function initialBasemapId() {
  const params = mapPageParams();
  const config = mapConfig();
  return normalizedBasemapId(params.get('basemap') || config.basemap || config.defaultBasemap || 'offline');
}

function setupBasemapControl() {
  const select = $('basemapSelect');
  if (!select) return;
  state.basemap = initialBasemapId();
  select.value = state.basemap;
}

function selectedBasemapId() {
  return normalizedBasemapId($('basemapSelect')?.value || state.basemap);
}

function localTileTemplate() {
  const params = mapPageParams();
  const config = mapConfig();
  return params.get('tiles') || config.localTileTemplate || BASEMAP_LOCAL_TEMPLATE;
}

function tiandituToken() {
  const params = mapPageParams();
  const config = mapConfig();
  return params.get('tdt_tk') || params.get('tk') || config.tiandituToken || config.tdtToken || '';
}

function tiandituTiles(layer, token) {
  return Array.from({ length: 8 }, (_, index) => {
    return `https://t${index}.tianditu.gov.cn/DataServer?T=${layer}&x={x}&y={y}&l={z}&tk=${encodeURIComponent(token)}`;
  });
}

function basemapDefinition(id) {
  if (id === 'local-xyz') {
    return {
      label: '内网瓦片',
      sources: [
        {
          id: BASEMAP_SOURCE_ID,
          definition: {
            type: 'raster',
            tiles: [localTileTemplate()],
            tileSize: 256,
            minzoom: 0,
            maxzoom: 12,
            attribution: '内网底图',
          },
        },
      ],
      layers: [
        {
          id: BASEMAP_LAYER_ID,
          type: 'raster',
          source: BASEMAP_SOURCE_ID,
          paint: {
            'raster-opacity': 0.74,
            'raster-saturation': -0.25,
          },
        },
      ],
      status: `底图：内网瓦片 ${localTileTemplate()}`,
    };
  }

  if (id === 'tdt-vector' || id === 'tdt-image') {
    const token = tiandituToken();
    if (!token) {
      return {
        label: '天地图',
        error: '天地图底图需要 tk：例如 ?basemap=tdt-vector&tdt_tk=你的Key',
      };
    }
    const baseLayer = id === 'tdt-image' ? 'img_w' : 'vec_w';
    const labelLayer = id === 'tdt-image' ? 'cia_w' : 'cva_w';
    return {
      label: id === 'tdt-image' ? '天地图影像' : '天地图矢量',
      sources: [
        {
          id: BASEMAP_SOURCE_ID,
          definition: {
            type: 'raster',
            tiles: tiandituTiles(baseLayer, token),
            tileSize: 256,
            minzoom: 0,
            maxzoom: 18,
            attribution: '天地图',
          },
        },
        {
          id: BASEMAP_LABEL_SOURCE_ID,
          definition: {
            type: 'raster',
            tiles: tiandituTiles(labelLayer, token),
            tileSize: 256,
            minzoom: 0,
            maxzoom: 18,
            attribution: '天地图注记',
          },
        },
      ],
      layers: [
        {
          id: BASEMAP_LAYER_ID,
          type: 'raster',
          source: BASEMAP_SOURCE_ID,
          paint: {
            'raster-opacity': id === 'tdt-image' ? 0.68 : 0.82,
            'raster-saturation': id === 'tdt-image' ? -0.12 : -0.35,
          },
        },
        {
          id: BASEMAP_LABEL_LAYER_ID,
          type: 'raster',
          source: BASEMAP_LABEL_SOURCE_ID,
          paint: {
            'raster-opacity': 0.82,
          },
        },
      ],
      status: `底图：${id === 'tdt-image' ? '天地图影像' : '天地图矢量'}`,
    };
  }

  return null;
}

function removeBasemap() {
  if (!map) return;
  [BASEMAP_LABEL_LAYER_ID, BASEMAP_LAYER_ID].forEach((layerId) => {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  });
  [BASEMAP_LABEL_SOURCE_ID, BASEMAP_SOURCE_ID].forEach((sourceId) => {
    if (map.getSource(sourceId)) map.removeSource(sourceId);
  });
}

function addLayerBefore(layer, beforeLayerId) {
  if (beforeLayerId && map.getLayer(beforeLayerId)) {
    map.addLayer(layer, beforeLayerId);
    return;
  }
  map.addLayer(layer);
}

function basemapLabelBeforeLayerId() {
  if (map.getLayer(CONTOUR_LAYER_ID)) return CONTOUR_LAYER_ID;
  if (map.getLayer(FEATURE_LAYER_IDS.polygonFill)) return FEATURE_LAYER_IDS.polygonFill;
  return undefined;
}

function applyBaseMap() {
  if (!map || !state.mapReady) return;
  const id = selectedBasemapId();
  state.basemap = id;
  removeBasemap();
  if (id === 'offline') {
    status('底图：离线简图（无外网请求）');
    return;
  }

  const definition = basemapDefinition(id);
  if (!definition) {
    status('底图：离线简图（无外网请求）');
    return;
  }
  if (definition.error) {
    status(definition.error);
    return;
  }

  definition.sources.forEach((source) => {
    map.addSource(source.id, source.definition);
  });
  definition.layers.forEach((layer) => {
    const beforeLayerId = layer.id === BASEMAP_LAYER_ID
      ? GRID_FILL_LAYER_ID
      : basemapLabelBeforeLayerId();
    addLayerBefore(layer, beforeLayerId);
  });
  status(definition.status || `底图：${definition.label}`);
}

function renderFeatureToggleGroup(boxId, items) {
  const box = $(boxId);
  if (!box) return;
  box.innerHTML = '';
  items.forEach(([type, label]) => {
    const color = featureColor(type);
    const el = document.createElement('label');
    el.dataset.featureType = type;

    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = type;
    input.checked = false;
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
  renderFeatureToggleGroup('featureToggles', weatherSystemFeatureTypes);
}

function setupAreaRiskControls() {
  const typeSelect = $('areaRiskTypeSelect');
  if (typeSelect) {
    typeSelect.innerHTML = '';
    areaRiskTypes.forEach(([type, label]) => {
      const option = document.createElement('option');
      option.value = type;
      option.textContent = label;
      typeSelect.appendChild(option);
    });
    typeSelect.value = 'short_duration_heavy_rain';
  }
  syncAreaRiskModeControls();
  renderAreaRiskList();
}

function syncAreaRiskModeControls() {
  const mode = $('areaRiskModeSelect')?.value || 'dominant';
  const typeSelect = $('areaRiskTypeSelect');
  if (typeSelect) typeSelect.disabled = mode !== 'single';
}

function appendAreaScopeOption(select, value, label, countText) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = countText ? `${label} (${countText})` : label;
  select.appendChild(option);
}

function populateAreaRiskScopes(catalog) {
  const select = $('areaRiskScopeSelect');
  if (!select) return;
  select.innerHTML = '';
  (catalog?.cities || []).forEach((city) => {
    appendAreaScopeOption(select, `city:${city.city_code}`, city.city_name, `${city.town_count}乡镇`);
  });
  (catalog?.counties || []).forEach((county) => {
    appendAreaScopeOption(select, `county:${county.county_code}`, `${county.city_name}·${county.county_name}`, `${county.town_count}乡镇`);
  });
  (catalog?.towns || []).forEach((town) => {
    appendAreaScopeOption(select, `town:${town.town_code}`, `${town.county_name}·${town.town_name}`, `${town.station_count || 0}站`);
  });
  if (!select.options.length) {
    appendAreaScopeOption(select, 'all:all', '全部区域', '');
  }
}

async function refreshAreaRiskCatalog() {
  const summary = $('areaRiskSummary');
  try {
    const catalog = await getEnvelope('/api/v1/diagnosis/nafp/areas');
    state.areaRiskCatalog = catalog;
    populateAreaRiskScopes(catalog);
    if (summary) summary.textContent = `${catalog.town_count || 0}个乡镇`;
  } catch (error) {
    state.areaRiskCatalog = null;
    populateAreaRiskScopes(null);
    if (summary) summary.textContent = '区域目录失败';
    console.warn('area risk catalog load failed', error);
  }
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

function selectedPointRunOption() {
  return $('pointRunTimeSelect')?.selectedOptions?.[0] || null;
}

function selectedPointRunIsSynthetic() {
  return selectedPointRunOption()?.dataset.synthetic === 'true';
}

function syntheticRunStatus(prefix = 'NAFP 原始格点') {
  return `${prefix}未自动加载：默认起报 ${formatPointRunTimeLabel(selectedPointRunTime())} 暂无本机数据，可切换 06-17 测试时次`;
}

function selectedLayerSource() {
  const source = $('layerSourceSelect')?.value || state.layerSource || 'nafp';
  return source === 'product' ? 'product' : 'nafp';
}

function selectedDataCategory() {
  return $('dataCategorySelect')?.value === 'sounding' ? 'sounding' : 'forecast';
}

function syncDataCategoryControls() {
  state.dataCategory = selectedDataCategory();
  const isSounding = state.dataCategory === 'sounding';
  document.querySelectorAll('.forecast-control').forEach((el) => { el.hidden = isSounding; });
  document.querySelectorAll('.sounding-control').forEach((el) => { el.hidden = !isSounding; });
  if (isSounding && state.pointProbeActive) setPointProbeActive(false);
}

function shouldUseNafpLayerSource() {
  return selectedLayerSource() === 'nafp';
}

function nafpPrecomputeKey(forecastHour = state.forecastHour) {
  if (!selectedPointRunTime()) return '';
  return [
    selectedPointDataCode(),
    selectedPointRunTime(),
    Number(forecastHour),
  ].join('|');
}

async function precomputeNafpSituation(forecastHour = state.forecastHour) {
  if (!shouldUseNafpLayerSource() || !selectedPointRunTime() || selectedPointRunIsSynthetic()) return null;
  const key = nafpPrecomputeKey(forecastHour);
  if (!key) return null;
  if (state.nafpPrecomputeKey === key && state.nafpPrecomputePromise) {
    return state.nafpPrecomputePromise;
  }

  const payload = {
    data_code: selectedPointDataCode(),
    run_time: selectedPointRunTime(),
    forecast_hours: [Number(forecastHour)],
  };
  state.nafpPrecomputeKey = key;
  state.nafpPrecomputePromise = postEnvelope('/api/v1/diagnosis/nafp/precompute', payload)
    .catch((error) => {
      if (state.nafpPrecomputeKey === key) state.nafpPrecomputeKey = '';
      console.warn('NAFP situation precompute failed', error);
      return null;
    })
    .finally(() => {
      if (state.nafpPrecomputeKey === key) state.nafpPrecomputePromise = null;
    });
  return state.nafpPrecomputePromise;
}

function scheduleNafpSituationPrecompute() {
  if (!shouldUseNafpLayerSource() || !selectedPointRunTime() || selectedPointRunIsSynthetic()) return;
  void precomputeNafpSituation();
}

async function waitForNafpPrecompute(forecastHour) {
  const key = nafpPrecomputeKey(forecastHour);
  if (key && state.nafpPrecomputeKey === key && state.nafpPrecomputePromise) {
    await state.nafpPrecomputePromise;
  }
}

function syncProductRunVisibility() {
  const field = document.querySelector('.run-field');
  if (field) field.hidden = selectedDataCategory() === 'sounding' || shouldUseNafpLayerSource();
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
    : [{ code: DEFAULT_POINT_DATA_CODE, label: 'ECTHIN', enabled: true }];
  sel.innerHTML = '';
  options.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.code;
    option.textContent = dataSourceLabel(item);
    sel.appendChild(option);
  });
  const preferred = defaultCode || state.pointDataCode || DEFAULT_POINT_DATA_CODE;
  sel.value = options.some((item) => item.code === preferred) ? preferred : options[0].code;
  state.pointDataCode = sel.value;
}

function populatePointRunTimes(payload) {
  const sel = $('pointRunTimeSelect');
  const sourceRuns = payload?.run_times || [];
  const preferred = pickDefaultRunTime({
    runTimes: sourceRuns,
    backendDefaultRunTime: payload?.default_run_time,
    currentRunTime: state.pointRunTime,
  });
  const runs = runTimesWithDefaultRunTime(sourceRuns, preferred, {
    fallbackRunTimes: LOCAL_TEST_RUN_TIMES,
  });
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
    if (run.synthetic) option.dataset.synthetic = 'true';
    sel.appendChild(option);
  });
  sel.value = runs.some((run) => run.run_time === preferred) ? preferred : runs[0].run_time;
  state.pointRunTime = sel.value;
  if (shouldUseNafpLayerSource()) syncForecastHoursFromPointRunTime();
  scheduleNafpSituationPrecompute();
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
  scheduleNafpSituationPrecompute();
  await loadLayer();
  await loadFeatures();
  if (state.areaRiskLoaded) await loadAreaRisks({ fitBounds: false });
}

function initializeMap() {
  if (!window.maplibregl) {
    status('MapLibre 加载失败，请检查本地静态资源');
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
    applyBaseMap();
    ensureReferenceOverlayLayer();
    ensureContourLayer();
    ensureFeatureLayers();
    ensureAreaRiskLayers();
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
  // Offline demos use the generated grid, contours, DOM place labels, and area
  // overlays only. This hook stays so the grid-loading order remains stable.
}

function ensureContourLayer() {
  if (!map || map.getSource(CONTOUR_SOURCE_ID)) return;
  map.addSource(CONTOUR_SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });
  map.addSource(CONTOUR_LABEL_SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });
  map.addLayer({
    id: CONTOUR_LAYER_ID,
    type: 'line',
    source: CONTOUR_SOURCE_ID,
    layout: {
      'line-cap': 'round',
      'line-join': 'round',
    },
    paint: {
      'line-color': contourColorExpression(),
      'line-width': ['interpolate', ['linear'], ['zoom'], 2, 1.1, 6, 2.2],
      'line-opacity': 0.86,
    },
  });
  map.addLayer({
    id: CONTOUR_LABEL_LAYER_ID,
    type: 'symbol',
    source: CONTOUR_LABEL_SOURCE_ID,
    layout: {
      'text-field': ['get', 'value_text'],
      'text-font': ['Noto Sans Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 2, 10, 5, 12, 8, 13],
      'text-allow-overlap': false,
      'text-ignore-placement': false,
      'text-padding': 3,
      'text-pitch-alignment': 'viewport',
      'text-rotation-alignment': 'viewport',
    },
    paint: {
      'text-color': '#253746',
      'text-halo-color': 'rgba(245, 250, 253, 0.9)',
      'text-halo-width': 1.35,
      'text-halo-blur': 0.35,
      'text-opacity': ['interpolate', ['linear'], ['zoom'], 2, 0.78, 4, 0.94],
    },
  });
  map.on('click', CONTOUR_LAYER_ID, (event) => {
    if (state.pointProbeActive) return;
    const feature = event.features?.[0];
    if (feature) selectContour(feature, event.lngLat);
  });
  map.on('mouseenter', CONTOUR_LAYER_ID, () => { map.getCanvas().style.cursor = 'crosshair'; });
  map.on('mouseleave', CONTOUR_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
  map.on('moveend', refreshContourLabelSource);
}

function isValidLngLatCoordinate(coordinate) {
  return Array.isArray(coordinate)
    && coordinate.length >= 2
    && Number.isFinite(Number(coordinate[0]))
    && Number.isFinite(Number(coordinate[1]));
}

function contourLineLength(coordinates) {
  if (!Array.isArray(coordinates) || coordinates.length < 2) return 0;
  return coordinates.slice(1).reduce((total, coordinate, index) => {
    const previous = coordinates[index];
    if (!isValidLngLatCoordinate(previous) || !isValidLngLatCoordinate(coordinate)) return total;
    const dx = Number(coordinate[0]) - Number(previous[0]);
    const dy = Number(coordinate[1]) - Number(previous[1]);
    return total + Math.hypot(dx, dy);
  }, 0);
}

function contourLineCoordinates(feature) {
  const geometry = feature?.geometry || {};
  const coordinates = geometry.coordinates || [];
  if (geometry.type === 'LineString') return coordinates;
  if (geometry.type === 'MultiLineString') {
    return coordinates
      .filter((line) => Array.isArray(line) && line.length)
      .sort((a, b) => contourLineLength(b) - contourLineLength(a))[0] || [];
  }
  return [];
}

function contourLabelCoordinate(feature) {
  const coordinates = contourLineCoordinates(feature).filter(isValidLngLatCoordinate);
  if (!coordinates.length) return null;
  const target = contourLineLength(coordinates) / 2;
  let traveled = 0;
  for (let index = 1; index < coordinates.length; index += 1) {
    const previous = coordinates[index - 1];
    const coordinate = coordinates[index];
    const segment = contourLineLength([previous, coordinate]);
    if (segment <= 0) continue;
    if (traveled + segment >= target) {
      const ratio = (target - traveled) / segment;
      return [
        Number(previous[0]) + (Number(coordinate[0]) - Number(previous[0])) * ratio,
        Number(previous[1]) + (Number(coordinate[1]) - Number(previous[1])) * ratio,
      ];
    }
    traveled += segment;
  }
  return coordinates[Math.floor(coordinates.length / 2)];
}

function contourLabelText(feature) {
  const props = feature?.properties || {};
  if (props.value_text) return String(props.value_text);
  if (props.value === undefined || props.value === null) return '';
  return formatValue(props.value, props.unit);
}

function contourLabelBounds() {
  if (!map || typeof map.getBounds !== 'function') return null;
  try {
    const bounds = map.getBounds();
    return {
      west: bounds.getWest() - CONTOUR_LABEL_BOUNDS_PADDING_DEGREES,
      south: bounds.getSouth() - CONTOUR_LABEL_BOUNDS_PADDING_DEGREES,
      east: bounds.getEast() + CONTOUR_LABEL_BOUNDS_PADDING_DEGREES,
      north: bounds.getNorth() + CONTOUR_LABEL_BOUNDS_PADDING_DEGREES,
    };
  } catch (error) {
    return null;
  }
}

function contourLabelCenter(bounds) {
  if (!bounds) return null;
  return [
    (Number(bounds.west) + Number(bounds.east)) / 2,
    (Number(bounds.south) + Number(bounds.north)) / 2,
  ];
}

function contourCoordinateInBounds(coordinate, bounds) {
  if (!bounds || !isValidLngLatCoordinate(coordinate)) return true;
  const lon = Number(coordinate[0]);
  const lat = Number(coordinate[1]);
  const withinLat = lat >= Number(bounds.south) && lat <= Number(bounds.north);
  if (!withinLat) return false;
  if (Number(bounds.west) <= Number(bounds.east)) {
    return lon >= Number(bounds.west) && lon <= Number(bounds.east);
  }
  return lon >= Number(bounds.west) || lon <= Number(bounds.east);
}

function contourCandidateDistance(first, second) {
  const firstCoordinate = Array.isArray(first?.coordinate) ? first.coordinate : first;
  const secondCoordinate = Array.isArray(second?.coordinate) ? second.coordinate : second;
  if (!isValidLngLatCoordinate(firstCoordinate) || !isValidLngLatCoordinate(secondCoordinate)) {
    return Number.POSITIVE_INFINITY;
  }
  const firstLon = Number(firstCoordinate[0]);
  const firstLat = Number(firstCoordinate[1]);
  const secondLon = Number(secondCoordinate[0]);
  const secondLat = Number(secondCoordinate[1]);
  const averageLatRadians = ((firstLat + secondLat) / 2) * Math.PI / 180;
  const dx = (firstLon - secondLon) * Math.cos(averageLatRadians);
  const dy = firstLat - secondLat;
  return Math.hypot(dx, dy);
}

function contourLabelTooClose(candidate, selected) {
  return selected.some((label) => {
    const distance = contourCandidateDistance(candidate, label);
    if (candidate.text === label.text) {
      return distance < CONTOUR_LABEL_SAME_VALUE_MIN_DISTANCE_DEGREES;
    }
    return distance < CONTOUR_LABEL_MIN_DISTANCE_DEGREES;
  });
}

function contourLabelCandidates(collection) {
  const bounds = contourLabelBounds();
  const center = contourLabelCenter(bounds);
  const candidates = (collection?.features || [])
    .map((feature) => {
      const coordinates = contourLineCoordinates(feature).filter(isValidLngLatCoordinate);
      const coordinate = contourLabelCoordinate(feature);
      const length = contourLineLength(coordinates);
      const text = contourLabelText(feature);
      const centerPenalty = center ? contourCandidateDistance(coordinate, center) * 0.04 : 0;
      return {
        coordinate,
        text,
        length,
        score: length - centerPenalty,
      };
    })
    .filter((label) => label.text && isValidLngLatCoordinate(label.coordinate) && label.length > 0)
    .map((label, index) => ({ ...label, id: `candidate-${index}` }));
  const visibleCandidates = candidates.filter((label) => contourCoordinateInBounds(label.coordinate, bounds));
  return visibleCandidates.length ? visibleCandidates : candidates;
}

function selectContourLabelCandidates(candidates) {
  const ranked = [...candidates].sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.length !== a.length) return b.length - a.length;
    return String(a.id).localeCompare(String(b.id));
  });
  const selected = [];
  const selectedIds = new Set();
  const selectedTexts = new Set();

  ranked.forEach((candidate) => {
    if (selected.length >= MAX_CONTOUR_LABELS || selectedTexts.has(candidate.text)) return;
    if (contourLabelTooClose(candidate, selected)) return;
    selected.push(candidate);
    selectedIds.add(candidate.id);
    selectedTexts.add(candidate.text);
  });

  ranked.forEach((candidate) => {
    if (selected.length >= MAX_CONTOUR_LABELS || selectedIds.has(candidate.id)) return;
    if (contourLabelTooClose(candidate, selected)) return;
    selected.push(candidate);
    selectedIds.add(candidate.id);
  });

  return selected;
}

function contourLabelFeatureCollection(collection) {
  const labels = selectContourLabelCandidates(contourLabelCandidates(collection));

  return {
    type: 'FeatureCollection',
    features: labels.map((label, index) => ({
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: label.coordinate,
      },
      properties: {
        id: `contour-label-${index}`,
        value_text: label.text,
      },
    })),
  };
}

function refreshContourLabelSource() {
  const source = map?.getSource(CONTOUR_LABEL_SOURCE_ID);
  if (!source || !state.contours || !$('contourToggle')?.checked) return;
  source.setData(contourLabelFeatureCollection(state.contours));
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
    layout: {
      'line-cap': 'round',
      'line-join': 'round',
    },
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
    layout: {
      'line-cap': 'round',
      'line-join': 'round',
    },
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

function ensureAreaRiskLayers() {
  if (!map || map.getSource(AREA_RISK_SOURCE_ID)) return;

  map.addSource(AREA_RISK_SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });
  map.addSource(AREA_RISK_BBOX_SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });

  map.addLayer({
    id: AREA_RISK_LAYER_IDS.selectedBbox,
    type: 'line',
    source: AREA_RISK_BBOX_SOURCE_ID,
    paint: {
      'line-color': '#f6b51f',
      'line-width': 2,
      'line-opacity': 0.9,
      'line-dasharray': [2, 1.4],
    },
  });

  map.addLayer({
    id: AREA_RISK_LAYER_IDS.halo,
    type: 'circle',
    source: AREA_RISK_SOURCE_ID,
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'score'], 0, 7, 0.5, 17, 1, 28],
      'circle-color': areaRiskColorExpression(),
      'circle-opacity': ['interpolate', ['linear'], ['get', 'score'], 0, 0.12, 0.5, 0.2, 1, 0.34],
      'circle-blur': 0.45,
    },
  });

  map.addLayer({
    id: AREA_RISK_LAYER_IDS.point,
    type: 'circle',
    source: AREA_RISK_SOURCE_ID,
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'score'], 0, 4.5, 0.5, 8, 1, 13],
      'circle-color': areaRiskColorExpression(),
      'circle-opacity': 0.9,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-opacity': 0.92,
      'circle-stroke-width': ['case', ['==', ['get', 'id'], ['literal', state.selectedAreaRiskId]], 3, 1.4],
    },
  });

  [AREA_RISK_LAYER_IDS.point].forEach((layerId) => {
    map.on('click', layerId, (event) => {
      if (state.pointProbeActive) return;
      const feature = event.features?.[0];
      if (feature) selectAreaRiskFeature(feature.properties?.id, event.lngLat);
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
  sel.value = state.layers.risk_short_duration_heavy_rain_score
    ? 'risk_short_duration_heavy_rain_score'
    : Object.keys(state.layers)[0] || '';
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

function pointRiskTargetOf(item) {
  return item?.target_type || item?.hazard_type || item?.feature_type || '';
}

function isPointRiskTarget(targetType) {
  const normalized = pointRiskTargetAliases.get(String(targetType || '')) || String(targetType || '');
  return pointRiskHazardTypes.has(normalized);
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
      <em>风险等级：${escapeHtml(levelLabel(level))}</em>
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

function pointRiskEvidenceChains(riskDiagnoses) {
  return (riskDiagnoses || [])
    .filter((risk) => isPointRiskTarget(pointRiskTargetOf(risk)))
    .map((risk) => ({
      target_type: pointRiskTargetOf(risk),
      level: risk.risk_level || risk.level,
      score: risk.score,
      evidence: risk.evidence || risk.dominant_evidence || [],
    }));
}

function bestPointRisk(result) {
  const risks = (result?.risk_diagnoses || []).filter((risk) => isPointRiskTarget(pointRiskTargetOf(risk)));
  if (!risks.length) return result?.scores?.[0] || null;
  return risks.reduce((best, risk) => {
    return Number(risk.score || 0) > Number(best.score || 0) ? risk : best;
  }, risks[0]);
}

function renderPointRiskChannelSection(channel, riskByHazard, renderedHazards = new Set()) {
  const cards = channel.hazards
    .filter((hazardType) => !renderedHazards.has(hazardType))
    .map((hazardType) => {
      const risk = riskByHazard.get(hazardType);
      if (risk) renderedHazards.add(hazardType);
      return risk;
    })
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

function renderPointEvidenceItem(item) {
  const threshold = item.threshold === null || item.threshold === undefined ? '-' : formatValue(item.threshold, item.unit);
  const value = item.value || formatValue(item.raw_value, item.unit);
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
  const conclusions = (result.diagnosis_conclusions || []).filter((item) => isPointRiskTarget(pointRiskTargetOf(item)));
  const riskDiagnoses = result.risk_diagnoses || [];
  const chains = pointRiskEvidenceChains(riskDiagnoses);
  const riskByHazard = riskDiagnosesByHazard(riskDiagnoses);
  const renderedHazards = new Set();
  const riskChannelHtml = pointRiskChannels
    .map((channel) => renderPointRiskChannelSection(channel, riskByHazard, renderedHazards))
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
    ${chains.length ? `
      <section class="point-chain-stack">
        ${chains.map(renderPointEvidenceChain).join('')}
      </section>
    ` : ''}
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
    const best = bestPointRisk(result);
    const bestType = best?.hazard_type || best?.feature_type || best?.target_type;
    popup
      .setLngLat([payload.lon, payload.lat])
      .setHTML(`<strong>点位诊断</strong><span>${targetLabel(bestType)} ${formatScore(best?.score)}</span>`)
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

function updateLegend(metadata, palette, domain = metadata) {
  $('legendTitle').textContent = metadata.title || metadata.layer_id || '诊断图层';
  $('legendMin').textContent = legendEndpointLabel(domain.min, metadata.unit, '低值');
  $('legendMax').textContent = legendEndpointLabel(domain.max, metadata.unit, '高值');
  $('legendRamp').style.background = `linear-gradient(90deg, ${palette.join(', ')})`;
  $('mapLegend').hidden = false;
}

async function loadLayer(options = {}) {
  if (!map || !state.mapReady) return;
  const layer = $('layerSelect').value;
  const fh = Number($('fhSelect').value);
  if (!layer || Number.isNaN(fh)) return;
  state.forecastHour = fh;
  if (selectedDataCategory() === 'sounding') {
    await loadSoundingLayerData(layer, options);
    return;
  }
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
  const domain = colorRampDomainForLayer(layer, md);
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(domain.min, domain.max, palette));
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-opacity', GRID_FILL_OPACITY);
  await loadContours();
  updateLegend(md, palette, domain);
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
  if (selectedPointRunIsSynthetic()) {
    status(syntheticRunStatus('NAFP 原始格点'));
    clearContours();
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
  const domain = colorRampDomainForLayer(layer, md);
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(domain.min, domain.max, palette));
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-opacity', GRID_FILL_OPACITY);
  await loadContours();
  updateLegend(md, palette, domain);
  renderLayerChips();
  if (options.fitBounds !== false) fitCurrentBounds({ duration: 450 });
  status(`已加载 NAFP 原始格点：${md.title || layer} +${fh}h`);
}

async function loadSoundingLayerData(layer) {
  const options = arguments[1] || {};
  if (layer !== 'z500') {
    selectDefaultSoundingLayer();
    layer = 'z500';
  }
  const title = state.layers[layer]?.title || layer;
  status(`正在加载 sounding 实况分析场：${title}`);

  const md = await getEnvelope(buildSoundingLayerMetadataUrl(layer, selectedSoundingCsvPath(), 500, Date.now()));
  state.currentBounds = metadataToBounds(md);
  const grid = await getEnvelope(buildSoundingLayerGridUrl(layer, selectedSoundingCsvPath(), 500, Date.now()));
  const source = map.getSource(GRID_SOURCE_ID);
  source.setData(grid);
  const palette = paletteForLayer(layer);
  const domain = colorRampDomainForLayer(layer, md);
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(domain.min, domain.max, palette));
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-opacity', SOUNDING_GRID_FILL_OPACITY);
  await loadContours();
  updateLegend(md, palette, domain);
  renderLayerChips();
  if (options.fitBounds !== false) fitCurrentBounds({ duration: 450 });
  status(`已加载 sounding 实况分析场：${md.title || layer}`);
}

function clearContours() {
  state.contours = null;
  const source = map?.getSource(CONTOUR_SOURCE_ID);
  if (source) source.setData({ type: 'FeatureCollection', features: [] });
  const labelSource = map?.getSource(CONTOUR_LABEL_SOURCE_ID);
  if (labelSource) labelSource.setData({ type: 'FeatureCollection', features: [] });
}

async function loadContours() {
  if (!map || !state.mapReady) return;
  if (!$('contourToggle')?.checked) {
    clearContours();
    return;
  }
  const layer = $('layerSelect').value;
  const fh = Number($('fhSelect').value);
  const useSounding = selectedDataCategory() === 'sounding';
  const useNafp = shouldUseNafpLayerSource();
  const runId = $('runSelect').value;
  if (!layer || Number.isNaN(fh)) {
    clearContours();
    return;
  }
  if (!useSounding && useNafp && !selectedPointRunTime()) {
    clearContours();
    return;
  }
  if (!useSounding && useNafp && selectedPointRunIsSynthetic()) {
    clearContours();
    return;
  }
  if (!useSounding && !useNafp && !runId) {
    clearContours();
    return;
  }
  try {
    let contours;
    if (useSounding) {
      contours = await getEnvelope(buildSoundingLayerContourUrl(layer, selectedSoundingCsvPath(), 500, Date.now()));
    } else if (useNafp) {
      contours = await getEnvelope(buildNafpLayerContourUrl(layer, selectedPointDataCode(), selectedPointRunTime(), fh, Date.now()));
    } else {
      contours = await api(buildLayerContourUrl(layer, runId, fh, Date.now()));
    }
    state.contours = contours;
    map.getSource(CONTOUR_SOURCE_ID).setData(contours);
    map.getSource(CONTOUR_LABEL_SOURCE_ID).setData(contourLabelFeatureCollection(contours));
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
  return [label, value, threshold].filter(Boolean).join(' | ');
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

function featureMetaRow(label, value) {
  if (value === null || value === undefined || value === '') return '';
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
}

function renderFrontClassificationMeta(props) {
  if (props.feature_type !== 'front_candidate') return '';
  return [
    featureMetaRow('锋面类型', props.front_type_label || featureDisplayLabel(props)),
    featureMetaRow('移向判据', props.front_motion_label),
    featureMetaRow(
      '分类置信度',
      props.front_type_confidence === null || props.front_type_confidence === undefined
        ? ''
        : Number(props.front_type_confidence).toFixed(2),
    ),
    featureMetaRow(
      '法向风',
      props.cross_front_wind_mean_ms === null || props.cross_front_wind_mean_ms === undefined
        ? ''
        : `${formatValue(props.cross_front_wind_mean_ms)} m/s`,
    ),
    featureMetaRow(
      '锋面轴长',
      props.axis_length_km === null || props.axis_length_km === undefined
        ? ''
        : `${formatValue(props.axis_length_km)} km`,
    ),
  ].join('');
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
        ${renderFrontClassificationMeta(props)}
      </dl>
      ${props.classification_reason && props.classification_reason !== props.diagnosis ? `<p class="object-diagnosis">${escapeHtml(props.classification_reason)}</p>` : ''}
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

function selectedAreaRiskMode() {
  return $('areaRiskModeSelect')?.value === 'single' ? 'single' : 'dominant';
}

function selectedAreaRiskType() {
  return $('areaRiskTypeSelect')?.value || 'short_duration_heavy_rain';
}

function selectedAreaRiskScope() {
  return $('areaRiskScopeSelect')?.value || 'all:all';
}

function areaRiskFeatureById(featureId) {
  return state.areaRiskFeatures.find((feature) => {
    return String(feature?.properties?.id || feature?.id || '') === String(featureId || '');
  });
}

function areaRiskColor(hazardType) {
  return areaRiskColors[hazardType] || '#32d5e7';
}

function formatDateTimeLabel(value) {
  const text = String(value || '');
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):?(\d{2})?/);
  if (!match) return text || '-';
  return `${match[2]}-${match[3]} ${match[4]}:${match[5] || '00'}`;
}

function updateAreaRiskSelectionPaint() {
  if (!map?.getLayer(AREA_RISK_LAYER_IDS.point)) return;
  map.setPaintProperty(AREA_RISK_LAYER_IDS.point, 'circle-stroke-width', [
    'case',
    ['==', ['get', 'id'], state.selectedAreaRiskId || ''],
    3,
    1.4,
  ]);
}

function areaRiskMapFeatureCollection(collection) {
  return {
    ...(collection || { type: 'FeatureCollection' }),
    features: (collection?.features || []).map((feature) => ({
      ...feature,
      properties: {
        ...(feature.properties || {}),
        bbox: JSON.stringify(feature.properties?.bbox || []),
        evidence_chain: '',
        metadata: '',
      },
    })),
  };
}

function bboxPolygonFeature(feature) {
  const props = feature?.properties || {};
  const bbox = parseFeatureProperty(props.bbox);
  const center = feature?.geometry?.coordinates || DEFAULT_CENTER;
  let minLon;
  let minLat;
  let maxLon;
  let maxLat;
  if (Array.isArray(bbox) && bbox.length === 4 && bbox.every((value) => Number.isFinite(Number(value)))) {
    [minLon, minLat, maxLon, maxLat] = bbox.map(Number);
  } else {
    const lon = Number(center[0]);
    const lat = Number(center[1]);
    minLon = lon - 0.04;
    maxLon = lon + 0.04;
    minLat = lat - 0.04;
    maxLat = lat + 0.04;
  }
  const lonPad = Math.max((maxLon - minLon) * 0.14, 0.025);
  const latPad = Math.max((maxLat - minLat) * 0.14, 0.025);
  minLon -= lonPad;
  maxLon += lonPad;
  minLat -= latPad;
  maxLat += latPad;
  return {
    type: 'Feature',
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [minLon, minLat],
        [maxLon, minLat],
        [maxLon, maxLat],
        [minLon, maxLat],
        [minLon, minLat],
      ]],
    },
    properties: { id: props.id || '' },
  };
}

function clearAreaRiskBbox() {
  map?.getSource(AREA_RISK_BBOX_SOURCE_ID)?.setData({ type: 'FeatureCollection', features: [] });
}

function clearAreaRisks(message = '区域风险已清空') {
  state.areaRiskFeatures = [];
  state.selectedAreaRiskId = '';
  state.areaRiskLoaded = false;
  map?.getSource(AREA_RISK_SOURCE_ID)?.setData({ type: 'FeatureCollection', features: [] });
  clearAreaRiskBbox();
  updateAreaRiskSelectionPaint();
  renderAreaRiskList();
  const summary = $('areaRiskSummary');
  if (summary) summary.textContent = '未加载';
  status(message);
}

function renderAreaRiskList() {
  const list = $('areaRiskList');
  const summary = $('areaRiskSummary');
  if (!list) return;
  list.innerHTML = '';
  if (!state.areaRiskFeatures.length) {
    const empty = document.createElement('div');
    empty.className = 'area-risk-empty';
    empty.textContent = state.areaRiskLoaded ? '当前时效无区域风险' : '选择区域后加载';
    list.appendChild(empty);
    if (summary && state.areaRiskLoaded) summary.textContent = '无风险点';
    return;
  }

  const topFeatures = state.areaRiskFeatures.slice(0, 12);
  if (summary) {
    const best = topFeatures[0]?.properties;
    summary.textContent = `${state.areaRiskFeatures.length}个区域 · 最高 ${formatScore(best?.score)}`;
  }
  topFeatures.forEach((feature) => {
    const props = feature.properties || {};
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `area-risk-item${props.id === state.selectedAreaRiskId ? ' active' : ''}`;
    button.dataset.areaRiskId = props.id;
    button.style.setProperty('--area-risk-color', areaRiskColor(props.hazard_type));

    const title = document.createElement('strong');
    title.textContent = props.town_name || props.county_name || '区域';
    const label = document.createElement('span');
    label.textContent = `${props.label || targetLabel(props.hazard_type)} · ${levelLabel(props.risk_level)}`;
    const score = document.createElement('em');
    score.textContent = formatScore(props.score);
    const meta = document.createElement('small');
    meta.textContent = `${formatDateTimeLabel(props.valid_time)} · ${props.county_name || props.city_name || ''}`;

    button.append(title, label, score, meta);
    button.addEventListener('click', () => selectAreaRiskFeature(props.id));
    list.appendChild(button);
  });
}

function areaRiskMetric(label, value) {
  return `
    <div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function areaRiskFactorItem(item) {
  return `
    <li class="area-risk-factor">
      <strong>${escapeHtml(item?.label || item?.field || item?.factor || '因子')}</strong>
      <span>贡献 ${formatScore(item?.mean_contribution)}</span>
    </li>
  `;
}

function renderAreaRiskDetailCard(feature) {
  const props = feature?.properties || {};
  const chain = props.evidence_chain || {};
  const factors = Array.isArray(chain.dominant_factors) ? chain.dominant_factors : [];
  const maxSample = chain.max_sample || {};
  return `
    <section class="object-detail-card area-risk-detail-card">
      <header class="object-detail-head">
        <div>
          <span>区域风险</span>
          <strong>${escapeHtml(props.town_name || props.county_name || '区域')}</strong>
        </div>
        <em class="object-quality-badge ${escapeHtml(props.risk_level || 'low')}">${escapeHtml(levelLabel(props.risk_level))}</em>
      </header>
      <div class="object-quality-strip ${escapeHtml(props.risk_level || 'low')}">
        ${areaRiskMetric('最高评分', formatScore(props.score))}
        ${areaRiskMetric('P90', formatScore(props.p90_score))}
        ${areaRiskMetric('均值', formatScore(props.mean_score))}
      </div>
      <dl class="object-meta-grid">
        <div><dt>风险类别</dt><dd>${escapeHtml(props.label || targetLabel(props.hazard_type))}</dd></div>
        <div><dt>有效时间</dt><dd>${escapeHtml(formatDateTimeLabel(props.valid_time))}</dd></div>
        <div><dt>乡镇</dt><dd>${escapeHtml(props.town_code || '-')}</dd></div>
        <div><dt>行政区</dt><dd>${escapeHtml([props.city_name, props.county_name].filter(Boolean).join('·') || '-')}</dd></div>
        <div><dt>源格点</dt><dd>${escapeHtml(props.source_grid || '-')}</dd></div>
        <div><dt>天气对象</dt><dd>${escapeHtml(props.feature_type || '-')}</dd></div>
      </dl>
    </section>
    <section class="feature-evidence-card area-risk-evidence-card">
      <header>
        <strong>证据链</strong>
        <span>${escapeHtml(chain.sampling_method || 'station_points')}</span>
      </header>
      <div class="area-risk-evidence-summary">
        ${areaRiskMetric('站点数', String(props.station_count ?? 0))}
        ${areaRiskMetric('采样数', String(props.sample_count ?? 0))}
        ${areaRiskMetric('评分来源', escapeHtml(chain.score_statistic || 'station_points_max'))}
      </div>
      ${maxSample.station_name ? `
        <p class="area-risk-max-sample">
          最大样本：${escapeHtml(maxSample.station_name)} ${escapeHtml(formatScore(maxSample.score))}
        </p>
      ` : ''}
      <ol class="area-risk-factor-list">
        ${factors.length ? factors.map(areaRiskFactorItem).join('') : '<li class="feature-evidence-empty">暂无主导因子。</li>'}
      </ol>
    </section>
  `;
}

function selectAreaRiskFeature(featureId, lngLat) {
  const feature = areaRiskFeatureById(featureId);
  if (!feature || !map) return;
  const props = feature.properties || {};
  state.selectedAreaRiskId = props.id || '';
  updateAreaRiskSelectionPaint();
  renderAreaRiskList();
  map.getSource(AREA_RISK_BBOX_SOURCE_ID)?.setData({
    type: 'FeatureCollection',
    features: [bboxPolygonFeature(feature)],
  });
  showObjectHtmlDetail('区域风险详情', renderAreaRiskDetailCard(feature));
  const center = feature.geometry?.coordinates || DEFAULT_CENTER;
  const popupLngLat = lngLat || center;
  popup
    .setLngLat(popupLngLat)
    .setHTML(`<strong>${escapeHtml(props.town_name || '区域风险')}</strong><span>${escapeHtml(props.label || targetLabel(props.hazard_type))} ${formatScore(props.score)}</span>`)
    .addTo(map);
  if (!lngLat) {
    map.flyTo({
      center,
      zoom: Math.max(map.getZoom(), 7),
      duration: 450,
    });
  }
}

function fitAreaRiskBounds(features) {
  const bounds = features
    .map((feature) => parseFeatureProperty(feature.properties?.bbox))
    .filter((bbox) => Array.isArray(bbox) && bbox.length === 4)
    .reduce((acc, bbox) => {
      const values = bbox.map(Number);
      if (!values.every(Number.isFinite)) return acc;
      if (!acc) return values;
      return [
        Math.min(acc[0], values[0]),
        Math.min(acc[1], values[1]),
        Math.max(acc[2], values[2]),
        Math.max(acc[3], values[3]),
      ];
    }, null);
  if (bounds) {
    const isNarrow = window.innerWidth <= 700;
    map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
      padding: isNarrow
        ? { top: 250, right: 18, bottom: 112, left: 18 }
        : { top: 118, right: 350, bottom: 108, left: 420 },
      maxZoom: 7.2,
      duration: 520,
    });
  }
}

async function loadAreaRisks(options = {}) {
  if (!map || !state.mapReady) return;
  if (!selectedPointRunTime()) {
    clearAreaRisks(`区域风险未就绪：${selectedPointDataCode()} 未发现起报时次`);
    return;
  }
  if (selectedPointRunIsSynthetic()) {
    clearAreaRisks(syntheticRunStatus('区域风险'));
    return;
  }
  const mode = selectedAreaRiskMode();
  const riskType = mode === 'single' ? selectedAreaRiskType() : '';
  const validTime = areaRiskValidTime(selectedPointRunTime(), Number($('fhSelect').value || state.forecastHour));
  const url = buildNafpAreaRiskUrl({
    dataCode: selectedPointDataCode(),
    runTime: selectedPointRunTime(),
    scopeValue: selectedAreaRiskScope(),
    validTime,
    riskType,
    cacheBust: Date.now(),
  });
  if (!url.startsWith(AREA_RISK_API_PATH)) console.warn(`unexpected area risk url: ${url}`);
  status(`正在加载区域风险：${formatDateTimeLabel(validTime)}`);
  try {
    const payload = await getEnvelope(url);
    const collection = areaRiskPayloadToFeatureCollection(payload, { mode, riskType });
    state.areaRiskFeatures = collection.features || [];
    state.selectedAreaRiskId = '';
    state.areaRiskLoaded = true;
    ensureAreaRiskLayers();
    map.getSource(AREA_RISK_SOURCE_ID).setData(areaRiskMapFeatureCollection(collection));
    clearAreaRiskBbox();
    updateAreaRiskSelectionPaint();
    renderAreaRiskList();
    if (options.fitBounds !== false && state.areaRiskFeatures.length) fitAreaRiskBounds(state.areaRiskFeatures);
    const summary = payload.summary || {};
    status(`已加载区域风险：${state.areaRiskFeatures.length}/${summary.town_count || state.areaRiskFeatures.length} 个区域`);
  } catch (error) {
    console.warn('area risk load failed', error);
    state.areaRiskFeatures = [];
    state.selectedAreaRiskId = '';
    state.areaRiskLoaded = true;
    map.getSource(AREA_RISK_SOURCE_ID)?.setData({ type: 'FeatureCollection', features: [] });
    clearAreaRiskBbox();
    renderAreaRiskList();
    status(`区域风险加载失败：${error.message}`);
  }
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
  return [...document.querySelectorAll(`#featureToggles ${selector}`)];
}

function selectedFeatureTypes() {
  return [...document.querySelectorAll('#featureToggles input:checked')]
    .map((input) => input.value);
}

function selectedSoundingCsvPath() {
  return $('soundingFileSelect')?.value || DEFAULT_SOUNDING_CSV_PATH;
}

function selectDefaultSoundingLayer() {
  if (!$('layerSelect') || !state.layers.z500) return;
  if ($('layerSelect').value !== 'z500') {
    $('layerSelect').value = 'z500';
    renderLayerChips();
  }
}

function isDenseSoundingRiskFeature(feature) {
  const props = feature?.properties || {};
  return props.score_source === 'sounding_profile_indices'
    && String(props.feature_type || '').endsWith('_risk');
}

function clearWeatherFeatures(message = '未选择天气系统，仅显示地图') {
  state.featureLoadToken += 1;
  state.features = [];
  state.selectedFeatureId = '';
  const featureSource = map?.getSource(FEATURE_SOURCE_ID);
  if (featureSource) featureSource.setData({ type: 'FeatureCollection', features: [] });
  clearPointMarkers();
  if (popup) popup.remove();
  showObjectDetail('对象详情', '未选择天气系统。');
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
  clearAreaRisks('未选择要素，仅显示地图');
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
    .filter((feature) => !isDenseSoundingRiskFeature(feature))
    .forEach((feature) => {
      const props = feature.properties || {};
      const [lon, lat] = feature.geometry.coordinates;
      const color = featureColor(props);
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

async function loadNafpFeatures(selected, fh, featureLoadToken) {
  if (!selectedPointRunTime()) {
    clearWeatherFeatures(`NAFP 对象未就绪：${selectedPointDataCode()} 未发现起报时次`);
    return;
  }
  if (selectedPointRunIsSynthetic()) {
    clearWeatherFeatures(syntheticRunStatus('NAFP 天气系统'));
    return;
  }
  status(`正在加载 ${selected.length} 类 NAFP 天气系统对象...`);
  try {
    await waitForNafpPrecompute(fh);
    const fc = await getEnvelope(buildNafpFeaturesUrl(selected, selectedPointDataCode(), selectedPointRunTime(), fh, Date.now()));
    if (featureLoadToken !== state.featureLoadToken) return;
    const displayFc = primaryFeatureCollection(fc);
    const smoothedFc = smoothFeatureCollectionForDisplay(displayFc);
    state.features = displayFc.features || [];
    state.selectedFeatureId = '';
    map.getSource(FEATURE_SOURCE_ID).setData(smoothedFc);
    renderPointMarkers(state.features);
    renderFeatureIndex();
    if (displayFc.properties?.summary) $('analysisText').textContent = displayFc.properties.summary;
    const totalFeatures = displayFc.properties?.total_features ?? state.features.length;
    const displayedFeatures = displayFc.properties?.displayed_features ?? state.features.length;
    status(`已加载 ${displayedFeatures}/${totalFeatures} 个 NAFP 天气系统对象`);
  } catch (error) {
    if (featureLoadToken !== state.featureLoadToken) return;
    console.warn('NAFP feature load failed', error);
    state.features = [];
    state.selectedFeatureId = '';
    map.getSource(FEATURE_SOURCE_ID).setData({ type: 'FeatureCollection', features: [] });
    clearPointMarkers();
    renderFeatureIndex();
    status(`NAFP 天气系统加载失败：${error.message}`);
  }
}

async function loadSoundingFeatures(selected = SOUNDING_DEFAULT_TYPES, featureLoadToken = ++state.featureLoadToken) {
  if (!map || !state.mapReady) return;
  status('正在加载 sounding 实况天气系统...');
  try {
    const fc = await getEnvelope(buildSoundingFeaturesUrl(selectedSoundingCsvPath(), 500, selected, Date.now()));
    if (featureLoadToken !== state.featureLoadToken) return;
    const displayFc = primaryFeatureCollection(fc);
    const smoothedFc = smoothFeatureCollectionForDisplay(displayFc);
    state.features = displayFc.features || [];
    state.selectedFeatureId = '';
    map.getSource(FEATURE_SOURCE_ID).setData(smoothedFc);
    renderPointMarkers(state.features);
    renderFeatureIndex();
    if (displayFc.properties?.summary) $('analysisText').textContent = displayFc.properties.summary;
    const domain = displayFc.properties?.domain || {};
    if (Number.isFinite(Number(domain.lon_min)) && Number.isFinite(Number(domain.lat_min))) {
      state.currentBounds = [domain.lon_min, domain.lat_min, domain.lon_max, domain.lat_max].map(Number);
      fitCurrentBounds({ maxZoom: 4.4 });
    }
    status(`已加载 ${state.features.length} 个 sounding 实况对象`);
  } catch (error) {
    if (featureLoadToken !== state.featureLoadToken) return;
    console.warn('sounding feature load failed', error);
    state.features = [];
    state.selectedFeatureId = '';
    map.getSource(FEATURE_SOURCE_ID).setData({ type: 'FeatureCollection', features: [] });
    clearPointMarkers();
    renderFeatureIndex();
    status(`sounding 实况加载失败：${error.message}`);
  }
}

async function loadFeatures() {
  if (!map || !state.mapReady) return;
  const featureLoadToken = ++state.featureLoadToken;
  const runId = $('runSelect').value;
  const fh = Number($('fhSelect').value);
  const selected = selectedFeatureTypes();
  if (!selected.length) {
    clearWeatherFeatures();
    return;
  }
  if (selectedDataCategory() === 'sounding') {
    await loadSoundingFeatures(selected, featureLoadToken);
    return;
  }
  if (shouldUseNafpLayerSource()) {
    await loadNafpFeatures(selected, fh, featureLoadToken);
    return;
  }
  status(`正在加载 ${selected.length} 类天气系统对象...`);

  const responses = await Promise.all(selected.map(async (type) => {
    try {
      return await api(`/api/features?run_id=${encodeURIComponent(runId)}&forecast_hour=${fh}&type=${type}`);
    } catch (e) {
      console.warn(`feature load failed: ${type}`, e);
      return null;
    }
  }));

  const fc = mergeFeatureCollections(responses);
  if (featureLoadToken !== state.featureLoadToken) return;
  state.features = fc.features;
  state.selectedFeatureId = '';
  map.getSource(FEATURE_SOURCE_ID).setData(fc);
  renderPointMarkers(state.features);
  renderFeatureIndex();
  status(`已加载 ${state.features.length} 个天气系统对象`);
}

async function handleFeatureToggleChange(event) {
  if (!event.target.matches('#featureToggles input[type="checkbox"]')) return;
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

async function runDiagnose() {
  status('诊断计算中，请稍候...');
  await api('/api/jobs/diagnose?model=ecmwf&file_path=data/raw/ecmwf_demo.nc&run_id=ecmwf_demo', { method: 'POST' });
  status('诊断完成');
  await refreshRuns();
  await loadLayer();
  await loadFeatures();
}

function wireEvents() {
  $('btnDiagnose').addEventListener('click', runDiagnose);
  $('dataCategorySelect').addEventListener('change', () => {
    syncDataCategoryControls();
    syncProductRunVisibility();
    if (state.dataCategory === 'sounding') selectDefaultSoundingLayer();
    clearWeatherFeatures(state.dataCategory === 'sounding' ? '已切换到实况，可加载 sounding 实况对象' : '已切换到数值模式预报');
  });
  $('btnPointProbe').addEventListener('click', () => {
    setPointProbeActive(!state.pointProbeActive);
  });
  $('btnLoadLayer').addEventListener('click', loadLayer);
  $('btnLoadAreaRisk').addEventListener('click', () => loadAreaRisks({ fitBounds: true }));
  $('btnLoadSoundingFeatures').addEventListener('click', () => loadSoundingFeatures());
  $('areaRiskScopeSelect').addEventListener('change', () => {
    if (state.areaRiskLoaded) loadAreaRisks({ fitBounds: true });
  });
  $('areaRiskModeSelect').addEventListener('change', () => {
    syncAreaRiskModeControls();
    if (state.areaRiskLoaded) loadAreaRisks({ fitBounds: false });
  });
  $('areaRiskTypeSelect').addEventListener('change', () => {
    if (state.areaRiskLoaded && selectedAreaRiskMode() === 'single') loadAreaRisks({ fitBounds: false });
  });
  $('featureToggles').addEventListener('change', handleFeatureToggleChange);
  $('btnClearOverlays').addEventListener('click', clearMapOverlays);
  $('basemapSelect').addEventListener('change', applyBaseMap);
  $('layerSourceSelect').addEventListener('change', async () => {
    state.layerSource = selectedLayerSource();
    syncProductRunVisibility();
    if (shouldUseNafpLayerSource()) {
      syncForecastHoursFromPointRunTime();
      scheduleNafpSituationPrecompute();
    }
    else await refreshForecastHours();
    await loadLayer();
    await loadFeatures();
    if (state.areaRiskLoaded) await loadAreaRisks({ fitBounds: false });
  });
  $('pointDataCodeSelect').addEventListener('change', async () => {
    await refreshPointRunTimes();
    if (shouldUseNafpLayerSource()) {
      syncForecastHoursFromPointRunTime();
      scheduleNafpSituationPrecompute();
      await loadLayer();
      if (state.areaRiskLoaded) await loadAreaRisks({ fitBounds: false });
    }
  });
  $('pointRunTimeSelect').addEventListener('change', async () => {
    state.pointRunTime = selectedPointRunTime();
    if (shouldUseNafpLayerSource()) {
      syncForecastHoursFromPointRunTime();
      scheduleNafpSituationPrecompute();
      await loadLayer();
      if (state.areaRiskLoaded) await loadAreaRisks({ fitBounds: false });
    }
  });
  $('runSelect').addEventListener('change', async () => {
    if (shouldUseNafpLayerSource()) state.runId = $('runSelect').value;
    else await refreshForecastHours();
    await loadLayer();
    await loadFeatures();
    if (state.areaRiskLoaded) await loadAreaRisks({ fitBounds: false });
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
  setupBasemapControl();
  setupAreaRiskControls();
  setupFeatureIndexControls();
  syncDataCategoryControls();
  wireEvents();
  syncProductRunVisibility();
  initializeMap();
  await refreshLayers();
  await refreshPointDataSources();
  await refreshAreaRiskCatalog();
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
