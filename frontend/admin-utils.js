(function attachAdminUtils(root, factory) {
  const utils = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = utils;
  }
  root.WeatherAdminUtils = utils;
})(typeof globalThis !== 'undefined' ? globalThis : window, function createAdminUtils() {
  const DEFAULT_FIELD_TOTAL = 18;

  const levelLabels = {
    high: '高',
    moderate: '中',
    low: '低',
  };

  const systemLabels = {
    subtropical_high: '副热带高压',
    trough_candidate: '槽线候选',
    ridge_candidate: '脊线候选',
    low_level_jet: '低空急流',
    front_candidate: '锋面候选',
    low_level_convergence: '低层辐合',
    upper_divergence: '高空辐散',
  };

  const chainLabels = {
    heavy_rain_potential: '强降水潜势',
    convection_potential: '强对流潜势',
  };

  function normalizeRunTime(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const isoLike = raw.replace(' ', 'T');
    if (/^\d{4}-\d{2}-\d{2}T\d{2}$/.test(isoLike)) {
      return `${isoLike}:00:00`;
    }
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(isoLike)) {
      return `${isoLike}:00`;
    }
    return isoLike;
  }

  function buildNafpSituationRequest(root, runTime, forecastHour) {
    return {
      root: String(root || '').trim(),
      run_time: normalizeRunTime(runTime),
      forecast_hour: Number(forecastHour),
    };
  }

  function summarizeSituation(payload) {
    const systems = payload?.systems || [];
    const chains = payload?.evidence_chains || [];
    const missing = payload?.missing_fields || [];
    const highRiskCount = chains.filter((chain) => chain.level === 'high').length;
    const moderateRiskCount = chains.filter((chain) => chain.level === 'moderate').length;
    const fieldTotal = Number(payload?.field_total) || DEFAULT_FIELD_TOTAL;
    const completeness = Math.max(0, Math.min(100, Math.round(((fieldTotal - missing.length) / fieldTotal) * 100)));
    return {
      systemCount: systems.length,
      highRiskCount,
      moderateRiskCount,
      missingCount: missing.length,
      completeness,
    };
  }

  function evidenceLevelLabel(level) {
    return levelLabels[level] || '未知';
  }

  function formatIsoForDuty(value) {
    if (!value) return '-';
    const match = String(value).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
    if (!match) return String(value);
    return `${match[1]} ${match[2]}:${match[3]}`;
  }

  function formatScore(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '-';
    return number.toFixed(2);
  }

  function formatPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '-';
    return `${number.toFixed(0)}%`;
  }

  function systemTypeLabel(type) {
    return systemLabels[type] || type || '天气系统';
  }

  function chainTypeLabel(type) {
    return chainLabels[type] || type || '诊断链';
  }

  function bboxLabel(regionOrGeometry) {
    const bbox = regionOrGeometry?.bbox || regionOrGeometry?.geometry?.bbox;
    if (!Array.isArray(bbox) || bbox.length !== 4) return '-';
    return bbox.map((item) => Number(item).toFixed(2)).join(', ');
  }

  return {
    bboxLabel,
    buildNafpSituationRequest,
    chainTypeLabel,
    evidenceLevelLabel,
    formatIsoForDuty,
    formatPercent,
    formatScore,
    normalizeRunTime,
    summarizeSituation,
    systemTypeLabel,
  };
});
