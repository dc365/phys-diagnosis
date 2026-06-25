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

  function buildOptionalQuery(params) {
    return params
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
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

  function parseLooseDateTime(value) {
    const text = String(value || '').trim();
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2})(?::?(\d{2}))?(?::?(\d{2}))?)?/);
    if (!match) return null;
    const [, year, month, day, hour = '00', minute = '00', second = '00'] = match;
    const date = new Date(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
    );
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function pad2(value) {
    return String(value).padStart(2, '0');
  }

  function formatLocalDateTime(date) {
    return [
      date.getFullYear(),
      pad2(date.getMonth() + 1),
      pad2(date.getDate()),
    ].join('-') + `T${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
  }

  function normalizeDateTime(value) {
    const date = parseLooseDateTime(value);
    return date ? formatLocalDateTime(date) : '';
  }

  function areaRiskValidTime(runTime, forecastHour) {
    const date = parseLooseDateTime(runTime);
    if (!date) return '';
    date.setHours(date.getHours() + Number(forecastHour || 0));
    return formatLocalDateTime(date);
  }

  function currentDay08RunTime(now = new Date()) {
    const date = new Date(now);
    date.setHours(8, 0, 0, 0);
    return formatLocalDateTime(date);
  }

  function pickDefaultRunTime(options = {}) {
    const runs = Array.isArray(options.runTimes) ? options.runTimes : [];
    const available = new Set(runs.map((run) => run?.run_time).filter(Boolean));
    const today08 = currentDay08RunTime(options.now);
    if (today08) return today08;
    if (options.currentRunTime && available.has(options.currentRunTime)) {
      return options.currentRunTime;
    }
    if (options.backendDefaultRunTime && available.has(options.backendDefaultRunTime)) {
      return options.backendDefaultRunTime;
    }
    return runs[0]?.run_time || '';
  }

  function runTimesWithDefaultRunTime(runTimes, defaultRunTime, options = {}) {
    const primaryRuns = Array.isArray(runTimes) ? runTimes.filter((run) => run?.run_time) : [];
    const fallbackRuns = Array.isArray(options.fallbackRunTimes)
      ? options.fallbackRunTimes.filter((run) => run?.run_time)
      : [];
    const seen = new Set();
    const runs = [...primaryRuns, ...fallbackRuns].filter((run) => {
      if (seen.has(run.run_time)) return false;
      seen.add(run.run_time);
      return true;
    });
    const target = String(defaultRunTime || '').trim();
    if (!target || runs.some((run) => run.run_time === target)) return runs;
    const fallbackHours = Array.isArray(runs[0]?.forecast_hours) ? runs[0].forecast_hours : [];
    return [
      {
        run_time: target,
        forecast_hours: [...fallbackHours],
        synthetic: true,
      },
      ...runs,
    ];
  }

  function areaRiskScopeParams(scopeValue) {
    const [scopeType, code] = String(scopeValue || '').split(':');
    if (!code || scopeType === 'all') return [];
    if (scopeType === 'town') return [['town_code', code]];
    if (scopeType === 'city' || scopeType === 'county') {
      return [['region_code', code], ['region_level', scopeType]];
    }
    return [];
  }

  function buildNafpAreaRiskUrl(options = {}) {
    const validTime = normalizeDateTime(options.validTime);
    const query = buildOptionalQuery([
      ['data_code', options.dataCode],
      ['run_time', normalizeDateTime(options.runTime) || options.runTime],
      ...areaRiskScopeParams(options.scopeValue),
      ['start_time', validTime],
      ['end_time', validTime],
      ['risk_type', options.riskType],
      ['_', options.cacheBust],
    ]);
    return `/api/v1/diagnosis/nafp/area-risks?${query}`;
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

  function isRiskScoreLayer(layerId) {
    const value = String(layerId || '');
    return value.startsWith('risk_') && value.endsWith('_score');
  }

  function colorRampDomainForLayer(layerId, metadata = {}) {
    if (isRiskScoreLayer(layerId)) return { min: 0, max: 1 };
    return { min: metadata.min, max: metadata.max };
  }

  function isScoreRangeUnit(unit) {
    const value = String(unit || '').trim();
    return value === '0-1' || value === 'risk_score';
  }

  function formatLegendNumber(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '无数据';
    const number = Number(value);
    if (Number.isInteger(number)) return String(number);
    return Math.abs(number) >= 100 ? number.toFixed(0) : number.toFixed(2);
  }

  function legendEndpointLabel(value, unit = '', prefix = '') {
    const text = formatLegendNumber(value);
    if (isScoreRangeUnit(unit)) return text;
    const valueText = unit ? `${text} ${unit}` : text;
    return prefix ? `${prefix} ${valueText}` : valueText;
  }

  function numberOrNull(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function validBbox(value) {
    if (!Array.isArray(value) || value.length !== 4) return null;
    const bbox = value.map(Number);
    return bbox.every(Number.isFinite) ? bbox : null;
  }

  function areaRiskCenter(area = {}) {
    const bbox = validBbox(area.bbox);
    if (bbox) return [
      Number(((bbox[0] + bbox[2]) / 2).toFixed(6)),
      Number(((bbox[1] + bbox[3]) / 2).toFixed(6)),
    ];
    const lon = numberOrNull(area.lon ?? area.longitude ?? area.center_lon);
    const lat = numberOrNull(area.lat ?? area.latitude ?? area.center_lat);
    if (lon !== null && lat !== null) return [lon, lat];
    return null;
  }

  function areaRiskScore(risk) {
    const score = numberOrNull(risk?.score ?? risk?.max_score);
    return score === null ? 0 : score;
  }

  function pickAreaRisk(risks, options = {}) {
    const items = Array.isArray(risks) ? risks : [];
    if (options.mode === 'single' && options.riskType) {
      return items.find((risk) => risk?.hazard_type === options.riskType) || null;
    }
    return [...items].sort((left, right) => areaRiskScore(right) - areaRiskScore(left))[0] || null;
  }

  function areaRiskPayloadToFeatureCollection(payload = {}, options = {}) {
    const mode = options.mode === 'single' ? 'single' : 'dominant';
    const features = [];
    (payload.items || []).forEach((item, itemIndex) => {
      const area = item?.area || {};
      const center = areaRiskCenter(area);
      const risk = pickAreaRisk(item?.risks, { mode, riskType: options.riskType });
      if (!center || !risk) return;
      const metadata = risk.metadata || payload.risk_metadata?.[risk.hazard_type] || {};
      const score = areaRiskScore(risk);
      const id = [
        area.town_code || `area-${itemIndex}`,
        item.valid_time || `fh-${item.forecast_hour ?? ''}`,
        risk.hazard_type || 'risk',
      ].join(':');
      features.push({
        type: 'Feature',
        id,
        geometry: { type: 'Point', coordinates: center },
        properties: {
          id,
          town_code: area.town_code || '',
          town_name: area.town_name || '',
          county_code: area.county_code || '',
          county_name: area.county_name || '',
          city_code: area.city_code || '',
          city_name: area.city_name || '',
          station_count: numberOrNull(risk.station_count ?? area.station_count) ?? 0,
          sample_count: numberOrNull(risk.sample_count) ?? 0,
          bbox: validBbox(area.bbox) || null,
          forecast_hour: numberOrNull(item.forecast_hour),
          valid_time: item.valid_time || '',
          hazard_type: risk.hazard_type || metadata.hazard_type || '',
          label: risk.label || metadata.label || risk.hazard_type || '风险',
          risk_level: risk.risk_level || risk.level || 'low',
          score,
          score_text: score.toFixed(3),
          max_score: numberOrNull(risk.max_score) ?? score,
          mean_score: numberOrNull(risk.mean_score) ?? 0,
          p90_score: numberOrNull(risk.p90_score) ?? 0,
          risk_domain: risk.risk_domain || metadata.risk_domain || '',
          source_grid: risk.source_grid || metadata.source_grid || '',
          feature_type: risk.feature_type || metadata.feature_type || '',
          evidence_chain: risk.evidence_chain || null,
          metadata,
        },
      });
    });
    features.sort((left, right) => Number(right.properties.score) - Number(left.properties.score));
    return {
      type: 'FeatureCollection',
      properties: {
        display_mode: mode,
        risk_type: mode === 'single' ? options.riskType || '' : '',
        item_count: payload.items?.length || 0,
        feature_count: features.length,
      },
      features,
    };
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

  function primaryFeatureCollection(collection) {
    const features = collection?.features || [];
    const hasPrimaryMetadata = features.some((feature) => {
      return typeof feature?.properties?.primary === 'boolean';
    });
    const displayFeatures = hasPrimaryMetadata
      ? features.filter((feature) => feature?.properties?.primary === true)
      : features;
    return {
      ...(collection || { type: 'FeatureCollection' }),
      type: 'FeatureCollection',
      properties: {
        ...(collection?.properties || {}),
        total_features: features.length,
        displayed_features: displayFeatures.length,
        display_filter: hasPrimaryMetadata ? 'primary' : 'all',
      },
      features: displayFeatures,
    };
  }

  function clonePoint(point) {
    return [Number(point?.[0]), Number(point?.[1])];
  }

  function isFinitePoint(point) {
    return Array.isArray(point)
      && point.length >= 2
      && Number.isFinite(Number(point[0]))
      && Number.isFinite(Number(point[1]));
  }

  function chaikinPair(left, right) {
    return [
      [
        left[0] * 0.75 + right[0] * 0.25,
        left[1] * 0.75 + right[1] * 0.25,
      ],
      [
        left[0] * 0.25 + right[0] * 0.75,
        left[1] * 0.25 + right[1] * 0.75,
      ],
    ];
  }

  function samePoint(left, right) {
    return left?.[0] === right?.[0] && left?.[1] === right?.[1];
  }

  function smoothOpenLineOnce(points) {
    if (!Array.isArray(points) || points.length < 3 || !points.every(isFinitePoint)) {
      return points;
    }
    const smoothed = [clonePoint(points[0])];
    for (let index = 0; index < points.length - 1; index += 1) {
      const [q, r] = chaikinPair(clonePoint(points[index]), clonePoint(points[index + 1]));
      smoothed.push(q, r);
    }
    smoothed.push(clonePoint(points[points.length - 1]));
    return smoothed;
  }

  function smoothClosedRingOnce(ring) {
    if (!Array.isArray(ring) || ring.length < 5 || !ring.every(isFinitePoint)) {
      return ring;
    }
    const source = ring.slice();
    if (samePoint(source[0], source[source.length - 1])) source.pop();
    if (source.length < 4) return ring;

    const smoothed = [];
    for (let index = 0; index < source.length; index += 1) {
      const current = clonePoint(source[index]);
      const next = clonePoint(source[(index + 1) % source.length]);
      const [q, r] = chaikinPair(current, next);
      smoothed.push(q, r);
    }
    smoothed.push(clonePoint(smoothed[0]));
    return smoothed;
  }

  function iterateSmooth(points, iterations, smoother) {
    let out = points;
    for (let index = 0; index < iterations; index += 1) {
      out = smoother(out);
    }
    return out;
  }

  function smoothGeometryForDisplay(geometry, options = {}) {
    const iterations = Math.max(1, Math.min(3, Number(options.iterations) || 1));
    if (!geometry || !geometry.type) return geometry;
    if (geometry.type === 'LineString') {
      return {
        ...geometry,
        coordinates: iterateSmooth(geometry.coordinates || [], iterations, smoothOpenLineOnce),
      };
    }
    if (geometry.type === 'Polygon') {
      return {
        ...geometry,
        coordinates: (geometry.coordinates || []).map((ring) => {
          return iterateSmooth(ring, iterations, smoothClosedRingOnce);
        }),
      };
    }
    if (geometry.type === 'MultiPolygon') {
      return {
        ...geometry,
        coordinates: (geometry.coordinates || []).map((polygon) => {
          return polygon.map((ring) => iterateSmooth(ring, iterations, smoothClosedRingOnce));
        }),
      };
    }
    return geometry;
  }

  function smoothFeatureCollectionForDisplay(collection, options = {}) {
    const features = collection?.features || [];
    return {
      ...(collection || { type: 'FeatureCollection' }),
      type: 'FeatureCollection',
      properties: {
        ...(collection?.properties || {}),
        geometry_smoothing: 'display-chaikin',
      },
      features: features.map((feature) => ({
        ...feature,
        geometry: smoothGeometryForDisplay(feature?.geometry, options),
        properties: { ...(feature?.properties || {}) },
      })),
    };
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
    areaRiskPayloadToFeatureCollection,
    areaRiskValidTime,
    boundsToImageCoordinates,
    buildNafpAreaRiskUrl,
    buildColorRampExpression,
    colorRampDomainForLayer,
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
  };
});
