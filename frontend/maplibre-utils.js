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
    return properties?.label || type || '对象';
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
    buildLayerImageUrl,
    buildLayerGridUrl,
    featureDisplayLabel,
    forecastHourLabel,
    mergeFeatureCollections,
    metadataToBounds,
    nextForecastHour,
  };
});
