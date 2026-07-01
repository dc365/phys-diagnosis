(function attachAdminUtils(root, factory) {
  const utils = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = utils;
  }
  root.WeatherAdminUtils = utils;
})(typeof globalThis !== 'undefined' ? globalThis : window, function createAdminUtils() {
  const DEFAULT_FIELD_TOTAL = 18;

  const levelLabels = {
    very_high: '很高',
    high: '高',
    moderate: '中',
    medium: '中',
    low: '低',
    very_low: '很低',
  };

  const systemLabels = {
    subtropical_high: '副热带高压',
    low_pressure_convergence: '低压辐合',
    high_pressure_divergence: '高压辐散',
    trough_candidate: '槽线候选',
    ridge_candidate: '脊线候选',
    low_level_jet: '低空急流',
    front_candidate: '锋面候选',
    low_level_convergence: '低层辐合',
    upper_divergence: '高空辐散',
    moisture_transport: '水汽输送',
    moisture_convergence: '水汽辐合',
  };

  const chainLabels = {
    heavy_rain_potential: '强降水潜势',
    convection_potential: '强对流潜势',
    dynamic_lift_potential: '动力抬升潜势',
    precipitation_phase: '雨雪相态',
  };

  const riskLabels = {
    persistent_heavy_rain: '持续性强降水',
    short_duration_heavy_rain: '短时强降水',
    thunderstorm_gale: '雷暴大风/下击暴流',
    hail: '冰雹',
    rotating_storm_or_supercell: '旋转风暴/超级单体潜势',
    severe_convection_composite: '强对流综合风险',
  };

  const systemTypeOrder = [
    'subtropical_high',
    'trough_candidate',
    'ridge_candidate',
    'front_candidate',
    'low_level_jet',
    'low_level_convergence',
    'upper_divergence',
    'moisture_transport',
    'moisture_convergence',
  ];
  const auxiliarySystemTypes = new Set(['low_pressure_convergence', 'high_pressure_divergence']);

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

  function formatDateTimeLocal(date) {
    const pad = (value) => String(value).padStart(2, '0');
    return [
      date.getFullYear(),
      pad(date.getMonth() + 1),
      pad(date.getDate()),
    ].join('-') + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function buildDefaultTimeWindow(now = new Date()) {
    const base = new Date(now);
    base.setHours(8, 0, 0, 0);
    const end = new Date(base);
    end.setDate(end.getDate() + 1);
    return {
      runTime: formatDateTimeLocal(base),
      startTime: formatDateTimeLocal(base),
      endTime: formatDateTimeLocal(end),
    };
  }

  function buildNafpSituationRequest(dataCode, runTime, forecastHour) {
    return {
      data_code: String(dataCode || '').trim(),
      run_time: normalizeRunTime(runTime),
      forecast_hour: Number(forecastHour),
    };
  }

  function normalizeForecastHours(values) {
    const source = Array.isArray(values) ? values : [values];
    const seen = new Set();
    const hours = [];
    source.forEach((item) => {
      const hour = Number(item);
      if (!Number.isFinite(hour) || seen.has(hour)) return;
      seen.add(hour);
      hours.push(hour);
    });
    return hours;
  }

  function buildNafpSituationBatchRequest(dataCode, runTime, forecastHours) {
    return {
      data_code: String(dataCode || '').trim(),
      run_time: normalizeRunTime(runTime),
      forecast_hours: normalizeForecastHours(forecastHours),
    };
  }

  function buildAreaRiskQuery({
    dataCode,
    runTime,
    scopeValue,
    startTime,
    endTime,
    forecastHourStart,
    forecastHourEnd,
    riskType,
  }) {
    const params = new URLSearchParams();
    params.set('data_code', String(dataCode || '').trim());
    params.set('run_time', normalizeRunTime(runTime));
    const [scopeType, scopeCode] = String(scopeValue || '').split(':');
    if (scopeType === 'town') {
      params.set('town_code', scopeCode || '');
    } else {
      params.set('region_code', scopeCode || '');
      params.set('region_level', scopeType || 'city');
    }
    if (startTime && endTime) {
      params.set('start_time', normalizeRunTime(startTime));
      params.set('end_time', normalizeRunTime(endTime));
    } else {
      if (forecastHourStart !== undefined && forecastHourStart !== '') {
        params.set('forecast_hour_start', String(Number(forecastHourStart)));
      }
      if (forecastHourEnd !== undefined && forecastHourEnd !== '') {
        params.set('forecast_hour_end', String(Number(forecastHourEnd)));
      }
    }
    if (riskType) params.set('risk_type', riskType);
    return `/api/v1/diagnosis/nafp/area-risks?${params.toString()}`;
  }

  function buildSoundingAreaRiskQuery({
    csvPath,
    pressureLevel = 500,
    scopeValue,
    riskType,
  }) {
    const params = new URLSearchParams();
    params.set('csv_path', String(csvPath || '').trim());
    params.set('pressure_level', String(Number(pressureLevel) || 500));
    const [scopeType, scopeCode] = String(scopeValue || '').split(':');
    if (scopeType === 'town') {
      params.set('town_code', scopeCode || '');
    } else {
      params.set('region_code', scopeCode || '');
      params.set('region_level', scopeType || 'city');
    }
    if (riskType) params.set('risk_type', riskType);
    return `/api/v1/sounding/area-risks?${params.toString()}`;
  }

  function summarizeSituation(payload) {
    const systems = visibleDutySystems(payload?.systems || []);
    const risks = payload?.risk_diagnoses || [];
    const missing = payload?.missing_fields || [];
    const riskLevel = (item) => item?.risk_level || item?.level || '';
    const highRiskCount = risks.filter((risk) => ['very_high', 'high'].includes(riskLevel(risk))).length;
    const moderateRiskCount = risks.filter((risk) => ['moderate', 'medium'].includes(riskLevel(risk))).length;
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

  function flattenAreaRiskRows(payload) {
    const rows = [];
    const dataType = payload?.data_type || 'forecast';
    (payload?.items || []).forEach((item) => {
      const area = item.area || {};
      (item.risks || []).forEach((risk) => {
        const hazardType = risk.hazard_type || '';
        const row = {
          ...risk,
          area,
          town_code: area.town_code,
          town_name: area.town_name,
          county_name: area.county_name,
          city_name: area.city_name,
          data_type: dataType,
          forecast_hour: item.forecast_hour,
          valid_time: item.valid_time,
          hazard_type: hazardType,
          label: risk.label || riskTypeLabel(hazardType),
          score: Number(risk.score),
          rowKey: `${dataType}|${area.town_code || '-'}|${item.forecast_hour}|${hazardType}`,
        };
        rows.push(row);
      });
    });
    return rows.sort((left, right) => {
      const scoreDelta = (Number(right.score) || 0) - (Number(left.score) || 0);
      if (scoreDelta) return scoreDelta;
      const hourDelta = (Number(left.forecast_hour) || 0) - (Number(right.forecast_hour) || 0);
      if (hourDelta) return hourDelta;
      return String(left.town_name || '').localeCompare(String(right.town_name || ''), 'zh-Hans-CN');
    });
  }

  function summarizeAreaRiskPayload(payload) {
    const rows = flattenAreaRiskRows(payload);
    const highRiskCount = rows.filter((row) => ['very_high', 'high'].includes(row.risk_level || row.level)).length;
    const maxRow = rows[0] || null;
    const townCount = Number(payload?.summary?.town_count)
      || new Set(rows.map((row) => row.town_code).filter(Boolean)).size;
    return {
      townCount,
      riskCount: rows.length,
      highRiskCount,
      maxScore: maxRow ? Number(maxRow.score) : 0,
      leadingRiskLabel: maxRow ? (maxRow.label || riskTypeLabel(maxRow.hazard_type)) : '-',
    };
  }

  function groupSystemsForDuty(systems, previewLimit = 4) {
    const byType = new Map();
    for (const system of visibleDutySystems(systems)) {
      const type = system?.type || 'unknown';
      if (!byType.has(type)) byType.set(type, []);
      byType.get(type).push(system);
    }
    return [...byType.entries()]
      .sort(([left], [right]) => {
        const leftIndex = systemTypeOrder.includes(left) ? systemTypeOrder.indexOf(left) : Number.MAX_SAFE_INTEGER;
        const rightIndex = systemTypeOrder.includes(right) ? systemTypeOrder.indexOf(right) : Number.MAX_SAFE_INTEGER;
        if (leftIndex !== rightIndex) return leftIndex - rightIndex;
        return String(left).localeCompare(String(right), 'zh-Hans-CN');
      })
      .map(([type, items]) => {
        const confidences = items
          .map((item) => Number(item?.confidence))
          .filter((value) => Number.isFinite(value));
        const averageConfidence = confidences.length
          ? Number((confidences.reduce((sum, value) => sum + value, 0) / confidences.length).toFixed(3))
          : 0;
        const levels = [...new Set(items.map((item) => item?.level).filter(Boolean))];
        const safeLimit = Math.max(1, Number(previewLimit) || 4);
        return {
          type,
          label: systemTypeLabel(type),
          count: items.length,
          items,
          previewItems: items.slice(0, safeLimit),
          remaining: Math.max(0, items.length - safeLimit),
          averageConfidence,
          levels,
        };
      });
  }

  function visibleDutySystems(systems) {
    return (systems || []).filter((system) => !auxiliarySystemTypes.has(system?.type));
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

  function riskTypeLabel(type) {
    return riskLabels[type] || type || '风险诊断';
  }

  function bboxLabel(regionOrGeometry) {
    const bbox = regionOrGeometry?.bbox || regionOrGeometry?.geometry?.bbox;
    if (!Array.isArray(bbox) || bbox.length !== 4) return '-';
    return bbox.map((item) => Number(item).toFixed(2)).join(', ');
  }

  return {
    bboxLabel,
    buildAreaRiskQuery,
    buildDefaultTimeWindow,
    buildNafpSituationBatchRequest,
    buildNafpSituationRequest,
    buildSoundingAreaRiskQuery,
    chainTypeLabel,
    evidenceLevelLabel,
    flattenAreaRiskRows,
    formatIsoForDuty,
    formatPercent,
    formatScore,
    groupSystemsForDuty,
    normalizeRunTime,
    riskTypeLabel,
    summarizeAreaRiskPayload,
    summarizeSituation,
    systemTypeLabel,
  };
});
