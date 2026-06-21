(function attachMapLibreUtils(root, factory) {
  const utils = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = utils;
  }
  root.WeatherMapUtils = utils;
})(typeof globalThis !== 'undefined' ? globalThis : window, function createMapLibreUtils() {
  function boundsToImageCoordinates(bounds) {
    const [minLon, minLat, maxLon, maxLat] = bounds;
    return [
      [minLon, maxLat],
      [maxLon, maxLat],
      [maxLon, minLat],
      [minLon, minLat],
    ];
  }

  function buildQuery(params) {
    return params
      .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
      .join('&');
  }

  function buildLayerImageUrl(layerId, runId, forecastHour, cacheBust) {
    const query = buildQuery([
      ['run_id', runId],
      ['forecast_hour', forecastHour],
      ['_', cacheBust],
    ]);
    return `/api/layers/${encodeURIComponent(layerId)}/image?${query}`;
  }

  function buildLayerGridUrl(layerId, runId, forecastHour, cacheBust) {
    const query = buildQuery([
      ['run_id', runId],
      ['forecast_hour', forecastHour],
      ['_', cacheBust],
    ]);
    return `/api/layers/${encodeURIComponent(layerId)}/grid?${query}`;
  }

  function buildLayerContourUrl(layerId, runId, forecastHour, cacheBust) {
    const query = buildQuery([
      ['run_id', runId],
      ['forecast_hour', forecastHour],
      ['_', cacheBust],
    ]);
    return `/api/layers/${encodeURIComponent(layerId)}/contours?${query}`;
  }

  function buildNafpLayerQuery(dataCode, runTime, forecastHour, cacheBust) {
    return buildQuery([
      ['data_code', dataCode],
      ['run_time', runTime],
      ['forecast_hour', forecastHour],
      ['_', cacheBust],
    ]);
  }

  function buildNafpLayerMetadataUrl(layerId, dataCode, runTime, forecastHour, cacheBust) {
    return `/api/v1/diagnosis/nafp/layers/${encodeURIComponent(layerId)}/metadata?${buildNafpLayerQuery(dataCode, runTime, forecastHour, cacheBust)}`;
  }

  function buildNafpLayerGridUrl(layerId, dataCode, runTime, forecastHour, cacheBust) {
    return `/api/v1/diagnosis/nafp/layers/${encodeURIComponent(layerId)}/grid?${buildNafpLayerQuery(dataCode, runTime, forecastHour, cacheBust)}`;
  }

  function buildNafpLayerContourUrl(layerId, dataCode, runTime, forecastHour, cacheBust) {
    return `/api/v1/diagnosis/nafp/layers/${encodeURIComponent(layerId)}/contours?${buildNafpLayerQuery(dataCode, runTime, forecastHour, cacheBust)}`;
  }

  function buildNafpFeaturesUrl(types, dataCode, runTime, forecastHour, cacheBust) {
    const query = buildQuery([
      ['data_code', dataCode],
      ['run_time', runTime],
      ['forecast_hour', forecastHour],
      ['types', (types || []).join(',')],
      ['_', cacheBust],
    ]);
    return `/api/v1/diagnosis/nafp/features?${query}`;
  }

  function buildColorRampExpression(min, max, colors) {
    const start = Number.isFinite(min) ? min : 0;
    const end = Number.isFinite(max) && max !== start ? max : start + 1;
    const expression = ['interpolate', ['linear'], ['get', 'value']];
    colors.forEach((color, index) => {
      const ratio = colors.length === 1 ? 0 : index / (colors.length - 1);
      expression.push(start + (end - start) * ratio, color);
    });
    return expression;
  }

  function featureDisplayLabel(properties) {
    const type = properties?.feature_type;
    if (type === 'high') return '高';
    if (type === 'low') return '低';
    if (type === 'low_pressure_convergence') return '低压辐合';
    if (type === 'high_pressure_divergence') return '高压辐散';
    return properties?.label || type || '对象';
  }

  function featureQuality(properties) {
    const confidence = Number(properties?.confidence);
    if (!Number.isFinite(confidence)) {
      return { level: 'pending', label: '待核验', scoreText: '-' };
    }
    const scoreText = confidence.toFixed(2);
    if (confidence >= 0.75) return { level: 'high', label: '高可信', scoreText };
    if (confidence >= 0.6) return { level: 'moderate', label: '中可信', scoreText };
    return { level: 'low', label: '低可信', scoreText };
  }

  function evidenceStrength(item) {
    const contribution = Number(item?.contribution);
    if (Number.isFinite(contribution)) return contribution;
    const normalized = Number(item?.normalized_score);
    const weight = Number(item?.weight);
    if (Number.isFinite(normalized) && Number.isFinite(weight)) return normalized * weight;
    if (Number.isFinite(normalized)) return normalized;
    if (Number.isFinite(weight)) return weight;
    return Number.NEGATIVE_INFINITY;
  }

  function rankFeatureEvidence(evidence) {
    return [...(Array.isArray(evidence) ? evidence : [])].sort((left, right) => {
      return evidenceStrength(right) - evidenceStrength(left);
    });
  }

  function collectCoordinatePairs(value, pairs = []) {
    if (!Array.isArray(value)) return pairs;
    if (
      value.length >= 2
      && typeof value[0] === 'number'
      && typeof value[1] === 'number'
    ) {
      pairs.push([value[0], value[1]]);
      return pairs;
    }
    value.forEach((item) => collectCoordinatePairs(item, pairs));
    return pairs;
  }

  function featureGeometryBounds(feature) {
    const pairs = collectCoordinatePairs(feature?.geometry?.coordinates);
    let minLon = Infinity;
    let minLat = Infinity;
    let maxLon = -Infinity;
    let maxLat = -Infinity;
    pairs.forEach(([lon, lat]) => {
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
      minLon = Math.min(minLon, lon);
      minLat = Math.min(minLat, lat);
      maxLon = Math.max(maxLon, lon);
      maxLat = Math.max(maxLat, lat);
    });
    if (!Number.isFinite(minLon)) return null;
    return [minLon, minLat, maxLon, maxLat];
  }

  const FEATURE_QUALITY_REVIEW_ORDER = {
    pending: 0,
    low: 1,
    moderate: 2,
    high: 3,
  };

  function featureIndexRows(features, filters = {}) {
    const typeFilter = filters.type && filters.type !== 'all' ? filters.type : '';
    const qualityFilter = filters.quality && filters.quality !== 'all' ? filters.quality : '';
    return (features || [])
      .map((feature, index) => {
        const props = feature?.properties || {};
        const quality = featureQuality(props);
        const confidence = Number(props.confidence);
        const featureType = props.feature_type || props.type || 'unknown';
        return {
          feature,
          id: props.id || `feature-${index}`,
          featureType,
          qualityLevel: quality.level,
          qualityLabel: quality.label,
          scoreText: quality.scoreText,
          confidence: Number.isFinite(confidence) ? confidence : null,
          label: featureDisplayLabel(props),
        };
      })
      .filter((row) => !typeFilter || row.featureType === typeFilter)
      .filter((row) => !qualityFilter || row.qualityLevel === qualityFilter)
      .sort((left, right) => {
        const leftOrder = FEATURE_QUALITY_REVIEW_ORDER[left.qualityLevel] ?? 99;
        const rightOrder = FEATURE_QUALITY_REVIEW_ORDER[right.qualityLevel] ?? 99;
        if (leftOrder !== rightOrder) return leftOrder - rightOrder;
        const leftConfidence = left.confidence ?? Infinity;
        const rightConfidence = right.confidence ?? Infinity;
        if (leftConfidence !== rightConfidence) return leftConfidence - rightConfidence;
        return String(left.id).localeCompare(String(right.id));
      });
  }

  const FEATURE_LAYER_RECOMMENDATIONS = {
    high: { candidates: ['mslp'], reason: 'pressure-center' },
    low: { candidates: ['mslp'], reason: 'pressure-center' },
    subtropical_high: { candidates: ['z500'], reason: '500hpa-height' },
    trough: { candidates: ['z500', 'vort500'], reason: '500hpa-height' },
    ridge: { candidates: ['z500'], reason: '500hpa-height' },
    low_pressure_convergence: { candidates: ['div850', 'mslp'], reason: 'low-level-divergence' },
    high_pressure_divergence: { candidates: ['div850', 'mslp'], reason: 'low-level-divergence' },
    low_level_convergence: { candidates: ['div850', 'moisture_conv850'], reason: 'low-level-divergence' },
    upper_divergence: { candidates: ['omega700', 'div850'], reason: 'upper-lift' },
    low_level_jet: { candidates: ['wind850_speed'], reason: 'low-level-wind' },
    moisture_transport: { candidates: ['moisture_flux850', 'moisture_conv850'], reason: 'moisture-transport' },
    front_candidate: { candidates: ['t850', 'temp_adv850', 'div850'], reason: 'thermal-front' },
    heavy_rain_risk: { candidates: ['heavy_rain_score', 'moisture_conv850', 'moisture_flux850'], reason: 'risk-score' },
    convection_risk: { candidates: ['convection_score', 'k_index', 'shear_0_6km'], reason: 'risk-score' },
    persistent_heavy_rain_risk: { candidates: ['risk_persistent_heavy_rain_score'], reason: 'risk-score' },
    short_duration_heavy_rain_risk: { candidates: ['risk_short_duration_heavy_rain_score'], reason: 'risk-score' },
    thunderstorm_gale_risk: { candidates: ['risk_thunderstorm_gale_score', 'risk_severe_convection_composite_score'], reason: 'risk-score' },
    hail_risk: { candidates: ['risk_hail_score', 'risk_severe_convection_composite_score'], reason: 'risk-score' },
    rotating_storm_risk: { candidates: ['risk_rotating_storm_score', 'risk_severe_convection_composite_score'], reason: 'risk-score' },
    severe_convection_composite_risk: { candidates: ['risk_severe_convection_composite_score'], reason: 'risk-score' },
  };

  function recommendedFeatureLayer(properties, availableLayerIds = []) {
    const type = properties?.feature_type || properties?.type || properties?.source_feature_type;
    const recommendation = FEATURE_LAYER_RECOMMENDATIONS[type];
    if (!recommendation) return null;
    const available = new Set(availableLayerIds || []);
    const layerId = available.size
      ? recommendation.candidates.find((candidate) => available.has(candidate))
      : recommendation.candidates[0];
    if (!layerId) return null;
    return { layerId, reason: recommendation.reason };
  }

  function forecastHourLabel(hour) {
    const value = Number(hour);
    if (value === 0) return '起报';
    return `+${value}小时`;
  }

  function nextForecastHour(hours, currentHour, direction) {
    const sorted = [...hours].map(Number).sort((a, b) => a - b);
    if (!sorted.length) return currentHour;
    const current = Number(currentHour);
    const index = sorted.indexOf(current);
    const safeIndex = index === -1 ? 0 : index;
    const nextIndex = Math.max(0, Math.min(sorted.length - 1, safeIndex + direction));
    return sorted[nextIndex];
  }

  function mergeFeatureCollections(collections) {
    return {
      type: 'FeatureCollection',
      features: collections.flatMap((collection) => collection?.features || []),
    };
  }

  function metadataToBounds(metadata) {
    return [metadata.lon_min, metadata.lat_min, metadata.lon_max, metadata.lat_max];
  }

  return {
    boundsToImageCoordinates,
    buildColorRampExpression,
    buildLayerContourUrl,
    buildLayerImageUrl,
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
  };
});
