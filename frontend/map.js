const DEFAULT_BOUNDS = [70, 15, 140, 55];
const DEFAULT_CENTER = [105, 35];
const GRID_SOURCE_ID = 'diagnostic-grid';
const GRID_FILL_LAYER_ID = 'diagnostic-grid-fill';
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
  layers: {},
  currentBounds: DEFAULT_BOUNDS,
  features: [],
  mapReady: false,
};

const featureTypes = [
  ['high', '高压中心'], ['low', '低压中心'], ['subtropical_high', '副高588区'],
  ['trough', '槽线候选'], ['ridge', '脊线候选'], ['low_level_convergence', '低层辐合区'],
  ['upper_divergence', '高空辐散区'], ['low_level_jet', '低空急流'],
  ['moisture_transport', '水汽输送带'], ['front_candidate', '锋面候选'],
  ['heavy_rain_risk', '强降水潜势'], ['convection_risk', '强对流潜势'],
];

const featureColors = {
  high: '#e03131',
  low: '#1c7ed6',
  subtropical_high: '#f59f00',
  trough: '#7c3aed',
  ridge: '#f08c00',
  low_level_convergence: '#0ca678',
  upper_divergence: '#15aabf',
  low_level_jet: '#d9480f',
  moisture_transport: '#228be6',
  front_candidate: '#495057',
  heavy_rain_risk: '#c92a2a',
  convection_risk: '#9c36b5',
};

const featureTypeNames = Object.fromEntries(featureTypes);

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
  buildColorRampExpression,
  buildLayerGridUrl,
  featureDisplayLabel,
  forecastHourLabel,
  mergeFeatureCollections,
  metadataToBounds,
  nextForecastHour,
} = window.WeatherMapUtils;

let map;
let popup;
let pointMarkers = [];
let placeMarkers = [];

function $(id) { return document.getElementById(id); }
function status(msg) { $('status').textContent = msg; }

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  return await r.json();
}

function colorMatchExpression() {
  const expression = ['match', ['get', 'feature_type']];
  Object.entries(featureColors).forEach(([type, color]) => expression.push(type, color));
  expression.push('#333333');
  return expression;
}

function createBaseStyle() {
  return {
    version: 8,
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

function setupFeatureToggles() {
  const box = $('featureToggles');
  box.innerHTML = '';
  featureTypes.forEach(([type, label]) => {
    const el = document.createElement('label');
    el.innerHTML = `<input type="checkbox" value="${type}" checked /> ${label}`;
    box.appendChild(el);
  });
}

function renderLayerChips() {
  const box = $('layerChips');
  if (!box) return;
  box.innerHTML = '';
  Object.entries(state.layers).forEach(([id, cfg]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `layer-chip${id === $('layerSelect').value ? ' active' : ''}`;
    button.textContent = cfg.title || id;
    button.addEventListener('click', async () => {
      $('layerSelect').value = id;
      renderLayerChips();
      await loadLayer();
    });
    box.appendChild(button);
  });
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
    ensureFeatureLayers();
    renderChinesePlaceLabels();
    fitCurrentBounds({ duration: 0 });
    status('MapLibre GIS 已就绪');
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
      'fill-opacity': 0.42,
    },
  });
  map.on('click', GRID_FILL_LAYER_ID, (event) => {
    const feature = event.features?.[0];
    if (feature) selectGridCell(feature, event.lngLat);
  });
  map.on('mouseenter', GRID_FILL_LAYER_ID, () => { map.getCanvas().style.cursor = 'crosshair'; });
  map.on('mouseleave', GRID_FILL_LAYER_ID, () => { map.getCanvas().style.cursor = ''; });
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
  await refreshForecastHours();
}

async function refreshForecastHours() {
  const runId = $('runSelect').value || state.runId;
  state.runId = runId;
  const sel = $('fhSelect');
  sel.innerHTML = '';
  try {
    const fhs = await api(`/api/forecast-times?run_id=${encodeURIComponent(runId)}`);
    state.forecastHours = fhs.map(Number);
    fhs.forEach((fh) => {
      const o = document.createElement('option');
      o.value = fh;
      o.textContent = forecastHourLabel(fh);
      sel.appendChild(o);
    });
    if (fhs.includes(state.forecastHour)) sel.value = state.forecastHour;
    else if (fhs.length) {
      state.forecastHour = fhs[0];
      sel.value = fhs[0];
    }
  } catch (e) {
    state.forecastHours = [0, 6, 12, 24, 36];
    [0, 6, 12, 24, 36].forEach((fh) => {
      const o = document.createElement('option');
      o.value = fh;
      o.textContent = forecastHourLabel(fh);
      sel.appendChild(o);
    });
  }
  renderTimeline();
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

function updateLegend(metadata, palette) {
  $('legendTitle').textContent = metadata.title || metadata.layer_id || '诊断图层';
  $('legendMin').textContent = `低值 ${formatValue(metadata.min, metadata.unit)}`;
  $('legendMax').textContent = `高值 ${formatValue(metadata.max, metadata.unit)}`;
  $('legendRamp').style.background = `linear-gradient(90deg, ${palette.join(', ')})`;
  $('mapLegend').hidden = false;
}

async function loadLayer() {
  if (!map || !state.mapReady) return;
  const layer = $('layerSelect').value;
  const runId = $('runSelect').value;
  const fh = Number($('fhSelect').value);
  if (!layer || !runId || Number.isNaN(fh)) return;

  state.runId = runId;
  state.forecastHour = fh;
  const title = state.layers[layer]?.title || layer;
  status(`正在加载 GIS 图层：${title} +${fh}h`);

  const md = await api(`/api/layers/${layer}/metadata?run_id=${encodeURIComponent(runId)}&forecast_hour=${fh}`);
  state.currentBounds = metadataToBounds(md);
  const grid = await api(buildLayerGridUrl(layer, runId, fh, Date.now()));
  const source = map.getSource(GRID_SOURCE_ID);
  source.setData(grid);
  const palette = paletteForLayer(layer);
  map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(md.min, md.max, palette));
  updateLegend(md, palette);
  renderLayerChips();
  fitCurrentBounds({ duration: 450 });
  status(`已加载 GIS 图层：${md.title || layer} +${fh}h`);
  await loadAnalysis();
}

function selectGridCell(feature, lngLat) {
  const props = feature.properties || {};
  const title = props.title || '诊断图层';
  const value = formatValue(props.value, props.unit);
  $('featureDetail').textContent = [
    `图层：${title}`,
    `格点值：${value}`,
    `行列：${props.row}, ${props.col}`,
  ].join('\n');
  popup
    .setLngLat(lngLat)
    .setHTML(`<strong>${title}</strong><span>格点值 ${value}</span>`)
    .addTo(map);
}

function selectFeature(feature, lngLat) {
  const props = feature.properties || {};
  $('featureDetail').textContent = formatFeatureDetail(props);
  const name = featureTypeNames[props.feature_type] || props.feature_type || '天气系统';
  const title = `${name} ${featureDisplayLabel(props)}`;
  const confidence = props.confidence === undefined ? '' : `<span>置信度 ${Number(props.confidence).toFixed(2)}</span>`;
  popup
    .setLngLat(lngLat)
    .setHTML(`<strong>${title}</strong>${confidence}`)
    .addTo(map);
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
  if (Array.isArray(props.evidence) && props.evidence.length) {
    lines.push('证据：');
    props.evidence.forEach((item) => lines.push(`- ${item}`));
  }
  return lines.join('\n');
}

function clearPointMarkers() {
  pointMarkers.forEach((marker) => marker.remove());
  pointMarkers = [];
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
        selectFeature(feature, [lon, lat]);
      });
      pointMarkers.push(
        new maplibregl.Marker({ element: el, anchor: 'left', offset: [12, 0] })
          .setLngLat([lon, lat])
          .addTo(map),
      );
    });
}

async function loadFeatures() {
  if (!map || !state.mapReady) return;
  const runId = $('runSelect').value;
  const fh = Number($('fhSelect').value);
  const selected = [...document.querySelectorAll('#featureToggles input:checked')].map((i) => i.value);
  status(`正在加载 ${selected.length} 类天气系统...`);

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
  map.getSource(FEATURE_SOURCE_ID).setData(fc);
  renderPointMarkers(state.features);
  status(`已加载 ${state.features.length} 个天气系统对象`);
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
  $('btnLoadLayer').addEventListener('click', loadLayer);
  $('btnLoadFeatures').addEventListener('click', loadFeatures);
  $('runSelect').addEventListener('change', async () => {
    await refreshForecastHours();
    await loadLayer();
    await loadFeatures();
  });
  $('fhSelect').addEventListener('change', () => setForecastHour(Number($('fhSelect').value)));
  $('btnStepPrev').addEventListener('click', () => {
    setForecastHour(nextForecastHour(state.forecastHours, state.forecastHour, -1));
  });
  $('btnStepNext').addEventListener('click', () => {
    setForecastHour(nextForecastHour(state.forecastHours, state.forecastHour, 1));
  });
}

async function init() {
  setupFeatureToggles();
  wireEvents();
  initializeMap();
  await refreshLayers();
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
