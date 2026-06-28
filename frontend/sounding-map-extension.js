(function attachSoundingMapExtension() {
  const FALLBACK_SOUNDING_LAYERS = {
    z500: { title: '500hPa 位势高度', unit: 'dagpm', variable: 'z500', data_type: 'sounding' },
  };
  const SOUNDING_RISK_TYPES = [
    'persistent_heavy_rain_risk',
    'short_duration_heavy_rain_risk',
    'thunderstorm_gale_risk',
    'hail_risk',
    'rotating_storm_risk',
    'severe_convection_composite_risk',
  ];
  const SOUNDING_SYSTEM_TYPES = [
    'high', 'low', 'warm_center', 'cold_center', 'trough', 'ridge',
    'shear_line', 'front_with_shear', 'low_level_jet', 'moisture_transport',
    'low_level_convergence', 'upper_divergence', 'upper_jet', 'cold_vortex',
    'mid_level_vortex', 'front_candidate',
  ];

  let forecastLayerSnapshot = null;

  function toQuery(params) {
    return params
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
      .join('&');
  }

  function isSoundingMode() {
    return (state?.dataCategory || document.getElementById('dataCategorySelect')?.value) === 'sounding';
  }

  function selectedCsv() {
    return typeof selectedSoundingCsvPath === 'function'
      ? selectedSoundingCsvPath()
      : (document.getElementById('soundingFileSelect')?.value || window.DEFAULT_SOUNDING_CSV_PATH || '');
  }

  async function getEnvelopeLocal(url) {
    if (typeof getEnvelope === 'function') return getEnvelope(url);
    const response = await fetch(url);
    const body = await response.json();
    if (!response.ok || body.code !== 0) throw new Error(body.msg || response.statusText);
    return body.data;
  }

  function copyLayers(layers) {
    return Object.fromEntries(Object.entries(layers || {}).map(([id, cfg]) => [id, { ...cfg }]));
  }

  function clearLayerObject(target) {
    Object.keys(target || {}).forEach((id) => delete target[id]);
  }

  function restoreForecastLayers() {
    if (!forecastLayerSnapshot || !state?.layers) return;
    clearLayerObject(state.layers);
    Object.assign(state.layers, copyLayers(forecastLayerSnapshot));
    forecastLayerSnapshot = null;
    if (typeof renderLayerChips === 'function') renderLayerChips();
  }

  function normalizeSoundingLayers(layers) {
    const normalized = {};
    Object.entries(layers || {}).forEach(([id, cfg]) => {
      if (!cfg) return;
      normalized[id] = {
        variable: cfg.variable || cfg.field || id,
        title: cfg.title || cfg.label || id,
        unit: cfg.unit || '',
        data_type: 'sounding',
      };
    });
    return Object.keys(normalized).length ? normalized : { ...FALLBACK_SOUNDING_LAYERS };
  }

  function replaceWithSoundingLayers(layers) {
    if (!state?.layers) return;
    if (!forecastLayerSnapshot) forecastLayerSnapshot = copyLayers(state.layers);
    const normalized = normalizeSoundingLayers(layers);
    clearLayerObject(state.layers);
    Object.assign(state.layers, normalized);

    const select = document.getElementById('layerSelect');
    if (select && !state.layers[select.value]) {
      select.value = state.layers.z500 ? 'z500' : Object.keys(state.layers)[0] || '';
    }
  }

  function layerAvailable(layerId) {
    return Boolean((state?.layers || {})[layerId]);
  }

  async function refreshSoundingLayers() {
    if (!isSoundingMode()) return;
    try {
      const data = await getEnvelopeLocal(`/api/v1/sounding/layers?${toQuery([['csv_path', selectedCsv()], ['pressure_level', 500], ['_', Date.now()]])}`);
      replaceWithSoundingLayers(data || {});
    } catch (error) {
      console.warn('sounding layer catalog load failed', error);
      replaceWithSoundingLayers(FALLBACK_SOUNDING_LAYERS);
    }
    if (typeof renderLayerChips === 'function') renderLayerChips();
  }

  function applySoundingFeatureVisibility() {
    const visible = new Set([...SOUNDING_SYSTEM_TYPES, ...SOUNDING_RISK_TYPES]);
    const sounding = isSoundingMode();
    document.querySelectorAll('#featureToggles label').forEach((label) => {
      const input = label.querySelector('input[type="checkbox"]');
      if (!input) return;
      label.hidden = sounding && !visible.has(input.value);
    });
  }

  function patchDefaultLayerSelection() {
    const original = window.selectDefaultSoundingLayer;
    window.selectDefaultSoundingLayer = function patchedSelectDefaultSoundingLayer() {
      if (!isSoundingMode()) return original?.();
      const select = document.getElementById('layerSelect');
      if (!select) return;
      if (!layerAvailable(select.value)) select.value = state.layers.z500 ? 'z500' : Object.keys(state.layers)[0] || '';
      if (typeof renderLayerChips === 'function') renderLayerChips();
    };
  }

  function patchSoundingLayerLoader() {
    const original = window.loadSoundingLayerData;
    window.loadSoundingLayerData = async function patchedLoadSoundingLayerData(layer, options = {}) {
      if (!map || !state.mapReady) return;
      await refreshSoundingLayers();
      const selectedLayer = layerAvailable(layer) ? layer : (state.layers.z500 ? 'z500' : Object.keys(state.layers)[0]);
      if (!selectedLayer) {
        status('当前探空时次没有可显示的实况要素');
        return;
      }
      const title = state.layers[selectedLayer]?.title || selectedLayer;
      status(`正在加载 sounding 实况分析场：${title}`);
      try {
        const md = await getEnvelopeLocal(buildSoundingLayerMetadataUrl(selectedLayer, selectedCsv(), 500, Date.now()));
        state.currentBounds = metadataToBounds(md);
        const grid = await getEnvelopeLocal(buildSoundingLayerGridUrl(selectedLayer, selectedCsv(), 500, Date.now()));
        map.getSource(GRID_SOURCE_ID).setData(grid);
        const palette = paletteForLayer(selectedLayer);
        const domain = colorRampDomainForLayer(selectedLayer, md);
        map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-color', buildColorRampExpression(domain.min, domain.max, palette));
        map.setPaintProperty(GRID_FILL_LAYER_ID, 'fill-opacity', SOUNDING_GRID_FILL_OPACITY);
        if (document.getElementById('layerSelect')) document.getElementById('layerSelect').value = selectedLayer;
        await loadContours();
        updateLegend(md, palette, domain);
        renderLayerChips();
        if (options.fitBounds !== false) fitCurrentBounds({ duration: 450 });
        status(`已加载 sounding 实况分析场：${md.title || selectedLayer}`);
      } catch (error) {
        if (typeof original === 'function' && selectedLayer === 'z500') return original(layer, options);
        status(`sounding 图层加载失败：${error.message}`);
        throw error;
      }
    };
  }

  function patchSoundingFeatureDefaults() {
    const original = window.loadSoundingFeatures;
    window.loadSoundingFeatures = async function patchedLoadSoundingFeatures(selected = null, token = ++state.featureLoadToken) {
      const types = selected && selected.length ? selected : [...SOUNDING_SYSTEM_TYPES, ...SOUNDING_RISK_TYPES];
      return original(types, token);
    };
  }

  function patchFeatureSetup() {
    const original = window.setupFeatureToggles;
    window.setupFeatureToggles = function patchedSetupFeatureToggles() {
      original();
      document.querySelectorAll('#featureToggles input').forEach((input) => {
        if ([...SOUNDING_SYSTEM_TYPES, ...SOUNDING_RISK_TYPES].includes(input.value)) input.dataset.sounding = 'true';
      });
      applySoundingFeatureVisibility();
    };
  }

  function bindSoundingEvents() {
    document.getElementById('dataCategorySelect')?.addEventListener('change', async () => {
      if (isSoundingMode()) await refreshSoundingLayers();
      else restoreForecastLayers();
      applySoundingFeatureVisibility();
    });
    document.getElementById('soundingFileSelect')?.addEventListener('change', async () => {
      if (!isSoundingMode()) return;
      await refreshSoundingLayers();
      await loadLayer({ fitBounds: false });
      await loadFeatures();
    });
  }

  patchDefaultLayerSelection();
  patchSoundingLayerLoader();
  patchSoundingFeatureDefaults();
  patchFeatureSetup();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      bindSoundingEvents();
      if (isSoundingMode()) refreshSoundingLayers();
      applySoundingFeatureVisibility();
    });
  } else {
    bindSoundingEvents();
    if (isSoundingMode()) refreshSoundingLayers();
    applySoundingFeatureVisibility();
  }
})();