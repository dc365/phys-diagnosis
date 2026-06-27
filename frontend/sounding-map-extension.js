(function attachSoundingMapExtension() {
  const DEFAULT_SOUNDING_LAYERS = {
    z500: { title: '500hPa 位势高度', unit: 'dagpm' },
    t500: { title: '500hPa 温度', unit: 'degC' },
    wind500_speed: { title: '500hPa 风速', unit: 'm/s' },
    vort500: { title: '500hPa 相对涡度', unit: 's^-1' },
    div500: { title: '500hPa 散度', unit: 's^-1' },
    t850: { title: '850hPa 温度', unit: 'degC' },
    td850: { title: '850hPa 露点', unit: 'degC' },
    rh850: { title: '850hPa 相对湿度', unit: '%' },
    q850: { title: '850hPa 比湿', unit: 'g/kg' },
    wind850_speed: { title: '850hPa 风速', unit: 'm/s' },
    div850: { title: '850hPa 散度', unit: 's^-1' },
    vort850: { title: '850hPa 相对涡度', unit: 's^-1' },
    moisture_flux850: { title: '850hPa 水汽通量', unit: 'g/kg*m/s' },
    t700: { title: '700hPa 温度', unit: 'degC' },
    rh700: { title: '700hPa 相对湿度', unit: '%' },
    wind700_speed: { title: '700hPa 风速', unit: 'm/s' },
    div700: { title: '700hPa 散度', unit: 's^-1' },
    lapse_rate_700_500: { title: '700-500hPa 温度递减率', unit: 'degC/km' },
    wind300_speed: { title: '300hPa 风速', unit: 'm/s' },
    div300: { title: '300hPa 散度', unit: 's^-1' },
    wind200_speed: { title: '200hPa 风速', unit: 'm/s' },
    div200: { title: '200hPa 散度', unit: 's^-1' },
    shear_850_500: { title: '850-500hPa 垂直风切变', unit: 'm/s' },
    risk_persistent_heavy_rain_score: { title: '探空持续性强降水风险', unit: '0-1' },
    risk_short_duration_heavy_rain_score: { title: '探空短时强降水风险', unit: '0-1' },
    risk_thunderstorm_gale_score: { title: '探空雷暴大风风险', unit: '0-1' },
    risk_hail_score: { title: '探空冰雹风险', unit: '0-1' },
    risk_rotating_storm_score: { title: '探空旋转风暴风险', unit: '0-1' },
    risk_severe_convection_composite_score: { title: '探空强对流综合风险', unit: '0-1' },
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

  function toQuery(params) {
    return params
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
      .join('&');
  }

  function selectedCsv() {
    return typeof selectedSoundingCsvPath === 'function'
      ? selectedSoundingCsvPath()
      : (document.getElementById('soundingFileSelect')?.value || window.DEFAULT_SOUNDING_CSV_PATH || '');
  }

  function layerAvailable(layerId) {
    return Boolean((state?.layers || {})[layerId] || DEFAULT_SOUNDING_LAYERS[layerId]);
  }

  async function getEnvelopeLocal(url) {
    if (typeof getEnvelope === 'function') return getEnvelope(url);
    const response = await fetch(url);
    const body = await response.json();
    if (!response.ok || body.code !== 0) throw new Error(body.msg || response.statusText);
    return body.data;
  }

  function mergeSoundingLayers(layers) {
    if (!state?.layers) return;
    Object.entries(layers || DEFAULT_SOUNDING_LAYERS).forEach(([id, cfg]) => {
      state.layers[id] = {
        ...(state.layers[id] || {}),
        variable: cfg.variable || cfg.field || id,
        title: cfg.title || cfg.label || id,
        unit: cfg.unit || state.layers[id]?.unit || '',
        data_type: 'sounding',
      };
    });
  }

  async function refreshSoundingLayers() {
    mergeSoundingLayers(DEFAULT_SOUNDING_LAYERS);
    try {
      const data = await getEnvelopeLocal(`/api/v1/sounding/layers?${toQuery([['csv_path', selectedCsv()], ['pressure_level', 500], ['_', Date.now()]])}`);
      mergeSoundingLayers(data || {});
    } catch (error) {
      console.warn('sounding layer catalog load failed', error);
    }
    if (typeof renderLayerChips === 'function') renderLayerChips();
  }

  function patchDefaultLayerSelection() {
    const original = window.selectDefaultSoundingLayer;
    window.selectDefaultSoundingLayer = function patchedSelectDefaultSoundingLayer() {
      const select = document.getElementById('layerSelect');
      if (!select) return;
      mergeSoundingLayers(DEFAULT_SOUNDING_LAYERS);
      if (!layerAvailable(select.value)) select.value = 'z500';
      if (!select.value) select.value = 'z500';
      if (typeof renderLayerChips === 'function') renderLayerChips();
      if (typeof original === 'function' && !layerAvailable(select.value)) original();
    };
  }

  function patchSoundingLayerLoader() {
    const original = window.loadSoundingLayerData;
    window.loadSoundingLayerData = async function patchedLoadSoundingLayerData(layer, options = {}) {
      if (!map || !state.mapReady) return;
      await refreshSoundingLayers();
      const selectedLayer = layerAvailable(layer) ? layer : 'z500';
      const title = state.layers[selectedLayer]?.title || DEFAULT_SOUNDING_LAYERS[selectedLayer]?.title || selectedLayer;
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
      // Existing checkboxes are shared by forecast and sounding because the
      // feature type names are intentionally aligned with NAFP diagnostics.
      // Mark sounding-relevant defaults so switching to 实况 gives useful output.
      document.querySelectorAll('#featureToggles input').forEach((input) => {
        if ([...SOUNDING_SYSTEM_TYPES, ...SOUNDING_RISK_TYPES].includes(input.value)) {
          input.dataset.sounding = 'true';
        }
      });
    };
  }

  function bindSoundingEvents() {
    document.getElementById('dataCategorySelect')?.addEventListener('change', () => {
      if (document.getElementById('dataCategorySelect')?.value === 'sounding') refreshSoundingLayers();
    });
    document.getElementById('soundingFileSelect')?.addEventListener('change', async () => {
      await refreshSoundingLayers();
      if (state.dataCategory === 'sounding') {
        await loadLayer({ fitBounds: false });
        await loadFeatures();
      }
    });
  }

  patchDefaultLayerSelection();
  patchSoundingLayerLoader();
  patchSoundingFeatureDefaults();
  patchFeatureSetup();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      bindSoundingEvents();
      refreshSoundingLayers();
    });
  } else {
    bindSoundingEvents();
    refreshSoundingLayers();
  }
})();
