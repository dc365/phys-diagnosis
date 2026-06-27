(function attachNafpPrecomputeMapExtension(root) {
  const utils = root.WeatherMapUtils;
  if (!utils || utils.__nafpPrecomputeMapExtension) return;

  function buildQuery(params) {
    return params
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
      .join('&');
  }

  utils.buildNafpFeaturesUrl = function buildPrecomputedNafpFeaturesUrl(types, dataCode, runTime, forecastHour, cacheBust) {
    const query = buildQuery([
      ['data_code', dataCode],
      ['run_time', runTime],
      ['forecast_hour', forecastHour],
      ['types', (types || []).join(',')],
      ['_', cacheBust],
    ]);
    return `/api/v1/diagnosis/nafp/precompute/features?${query}`;
  };

  utils.buildNafpPrecomputeStatusUrl = function buildNafpPrecomputeStatusUrl(cacheBust) {
    return `/api/v1/diagnosis/nafp/precompute/status?${buildQuery([['_', cacheBust]])}`;
  };

  utils.__nafpPrecomputeMapExtension = true;
})(typeof globalThis !== 'undefined' ? globalThis : window);
