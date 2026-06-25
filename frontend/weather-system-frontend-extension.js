(function attachWeatherSystemFrontendExtension(root) {
  const EXTRA_TYPES = [
    { type: 'shear_line', label: '切变线', color: '#2f9e44', kind: 'line', candidates: ['div850', 'wind850_speed', 'vort500'], reason: 'wind-shear-line' },
    { type: 'front_with_shear', label: '锋区切变线', color: '#7950f2', kind: 'line', candidates: ['t850', 'div850', 'temp_adv850'], reason: 'front-with-shear' },
    { type: 'low_level_convergence_axis', label: '低层辐合轴', color: '#087f5b', kind: 'line', candidates: ['div850', 'moisture_conv850'], reason: 'low-level-convergence-axis' },
    { type: 'upper_divergence_axis', label: '高空辐散轴', color: '#1098ad', kind: 'line', candidates: ['div200', 'div300', 'omega700'], reason: 'upper-divergence-axis' },
    { type: 'cold_vortex', label: '冷涡候选', color: '#364fc7', kind: 'point', candidates: ['z500', 'vort500', 't500'], reason: 'cold-vortex' },
    { type: 'mid_level_vortex', label: '低涡候选', color: '#1971c2', kind: 'point', candidates: ['z500', 'z700', 'vort500'], reason: 'mid-level-vortex' },
    { type: 'upper_jet', label: '高空急流', color: '#c2255c', kind: 'line', candidates: ['wind200_speed', 'wind300_speed', 'div200', 'div300'], reason: 'upper-jet' },
    { type: 'upper_jet_exit_region', label: '急流出口辐散区', color: '#e64980', kind: 'area', candidates: ['div200', 'div300', 'wind200_speed'], reason: 'jet-exit-divergence' },
    { type: 'pv_anomaly', label: '高空PV异常', color: '#6741d9', kind: 'area', candidates: ['pv300', 'pvadv300', 'rh500'], reason: 'upper-pv-anomaly' },
    { type: 'surface_front_candidate', label: '地面锋区候选', color: '#f03e3e', kind: 'line', candidates: ['t2m', 'td2m', 'mslp'], reason: 'surface-front-boundary' },
    { type: 'dryline_candidate', label: '干线候选', color: '#a16207', kind: 'line', candidates: ['td2m', 't2m', 'wind10_speed'], reason: 'dryline-boundary' },
  ];
  const EXTRA_BY_TYPE = Object.fromEntries(EXTRA_TYPES.map((item) => [item.type, item]));

  function looksLikeWeatherTypePairs(value) {
    if (!Array.isArray(value)) return false;
    const typeSet = new Set(value.filter(Array.isArray).map((item) => item[0]));
    return typeSet.has('high') && typeSet.has('low') && typeSet.has('subtropical_high') && typeSet.has('front_candidate');
  }

  function missingExtraPairs(value) {
    const existing = new Set((value || []).filter(Array.isArray).map((item) => item[0]));
    return EXTRA_TYPES.filter((item) => !existing.has(item.type)).map((item) => [item.type, item.label]);
  }

  function patchWeatherTypeIteration() {
    if (Array.prototype.__weatherSystemExtensionForEach) return;
    const originalForEach = Array.prototype.forEach;
    Object.defineProperty(Array.prototype, '__weatherSystemExtensionForEach', { value: true });
    Object.defineProperty(Array.prototype, 'forEach', {
      configurable: true,
      writable: true,
      value(callback, thisArg) {
        originalForEach.call(this, callback, thisArg);
        if (looksLikeWeatherTypePairs(this)) {
          missingExtraPairs(this).forEach((item, index) => {
            callback.call(thisArg, item, this.length + index, this);
          });
        }
      },
    });
  }

  function patchFeatureTypeNames() {
    if (Object.__weatherSystemExtensionFromEntries) return;
    const originalFromEntries = Object.fromEntries;
    Object.defineProperty(Object, '__weatherSystemExtensionFromEntries', { value: true });
    Object.fromEntries = function patchedFromEntries(iterable) {
      const entries = Array.from(iterable || []);
      const result = originalFromEntries(entries);
      if (looksLikeWeatherTypePairs(entries)) {
        EXTRA_TYPES.forEach((item) => {
          if (!result[item.type]) result[item.type] = item.label;
        });
      }
      return result;
    };
  }

  function patchFeatureColorEntries() {
    if (Object.__weatherSystemExtensionEntries) return;
    const originalEntries = Object.entries;
    Object.defineProperty(Object, '__weatherSystemExtensionEntries', { value: true });
    Object.entries = function patchedEntries(obj) {
      const entries = originalEntries(obj);
      if (
        obj
        && obj.high
        && obj.low
        && obj.subtropical_high
        && obj.front_candidate
        && obj.persistent_heavy_rain_risk
      ) {
        const existing = new Set(entries.map((item) => item[0]));
        EXTRA_TYPES.forEach((item) => {
          if (!existing.has(item.type)) entries.push([item.type, item.color]);
        });
      }
      return entries;
    };
  }

  function patchWeatherMapUtils() {
    const utils = root.WeatherMapUtils;
    if (!utils || utils.__weatherSystemExtensionPatched) return;
    const originalLabel = utils.featureDisplayLabel;
    const originalRecommendation = utils.recommendedFeatureLayer;

    utils.featureDisplayLabel = function extendedFeatureDisplayLabel(properties = {}) {
      const type = properties.feature_type || properties.source_feature_type || properties.type;
      const meta = EXTRA_BY_TYPE[type];
      if (meta) return properties.front_type_label || properties.label || properties.title || meta.label;
      return originalLabel(properties);
    };

    utils.recommendedFeatureLayer = function extendedRecommendedFeatureLayer(properties = {}, availableLayerIds = []) {
      const type = properties.feature_type || properties.source_feature_type || properties.type;
      const meta = EXTRA_BY_TYPE[type];
      if (meta) {
        const available = new Set(availableLayerIds || []);
        const layerId = available.size
          ? meta.candidates.find((candidate) => available.has(candidate))
          : meta.candidates[0];
        return layerId ? { layerId, reason: meta.reason } : null;
      }
      return originalRecommendation(properties, availableLayerIds);
    };

    utils.__weatherSystemExtensionPatched = true;
  }

  function featureColorMatchExpression() {
    const expression = ['match', ['get', 'feature_type']];
    EXTRA_TYPES.forEach((item) => expression.push(item.type, item.color));
    expression.push(['match', ['get', 'feature_type'], '#333333']);
    return expression;
  }

  function patchMapLibreFeatureLayerColors() {
    const maplibre = root.maplibregl;
    if (!maplibre?.Map?.prototype || maplibre.Map.prototype.__weatherSystemExtensionAddLayer) return;
    const originalAddLayer = maplibre.Map.prototype.addLayer;
    maplibre.Map.prototype.addLayer = function patchedAddLayer(layer, beforeId) {
      if (layer?.source === 'weather-features' && layer.paint) {
        const expression = featureColorMatchExpression();
        if (Object.prototype.hasOwnProperty.call(layer.paint, 'line-color')) layer.paint['line-color'] = expression;
        if (Object.prototype.hasOwnProperty.call(layer.paint, 'fill-color')) layer.paint['fill-color'] = expression;
        if (Object.prototype.hasOwnProperty.call(layer.paint, 'circle-color')) layer.paint['circle-color'] = expression;
      }
      return originalAddLayer.call(this, layer, beforeId);
    };
    maplibre.Map.prototype.__weatherSystemExtensionAddLayer = true;
  }

  function styleExtendedToggle(toggle) {
    const input = toggle.querySelector('input[type="checkbox"]');
    if (!input) return;
    const meta = EXTRA_BY_TYPE[input.value];
    if (!meta) return;
    input.style.accentColor = meta.color;
    const swatch = toggle.querySelector('.feature-swatch');
    if (swatch) {
      swatch.style.setProperty('--feature-color', meta.color);
      swatch.classList.remove('feature-swatch-area', 'feature-swatch-line', 'feature-swatch-point');
      swatch.classList.add(`feature-swatch-${meta.kind}`);
    }
    const label = toggle.querySelector('.feature-label');
    if (label) label.textContent = meta.label;
  }

  function applyToggleStyles() {
    const box = document.getElementById('featureToggles');
    if (!box) return;
    box.querySelectorAll('label').forEach(styleExtendedToggle);
  }

  function watchToggleStyles() {
    const box = document.getElementById('featureToggles');
    if (!box || box.__weatherSystemExtensionObserved) return;
    box.__weatherSystemExtensionObserved = true;
    const observer = new MutationObserver(applyToggleStyles);
    observer.observe(box, { childList: true, subtree: true });
    applyToggleStyles();
  }

  patchWeatherTypeIteration();
  patchFeatureTypeNames();
  patchFeatureColorEntries();
  patchWeatherMapUtils();
  patchMapLibreFeatureLayerColors();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watchToggleStyles, { once: true });
  } else {
    watchToggleStyles();
  }
  root.WeatherSystemFrontendExtension = { EXTRA_TYPES, EXTRA_BY_TYPE };
})(typeof globalThis !== 'undefined' ? globalThis : window);
