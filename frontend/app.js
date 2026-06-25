const DEFAULT_DATA_CODE = 'NAFP_ECTHIN_NC';
const DEFAULT_FORECAST_HOUR = 24;
const DEFAULT_VIEW = 'system-overview';
const DEFAULT_FORECAST_HOURS = Array.from({ length: 81 }, (_, index) => index * 3);
const FIELD_ORDER = [
  'gh500', 'uv500', 'uv850', 'q850', 'rh850', 'div850',
  'ttadv850', 'div200', 'div300', 'pv300', 'pvadv300', 'w700',
  'kindex', 'cape', 'cin', 'tcwv', 'rain6', 'shr850-200',
];
const GOVERNANCE_DOMAINS = {
  'weather-systems': {
    label: '天气系统',
    summary: '天气系统治理聚焦高低压、槽脊、副高、急流、水汽输送、辐合和锋面候选的识别规则。',
  },
  'risk-diagnosis': {
    label: '风险诊断',
    summary: '风险诊断治理聚焦六类风险评分、主导因子、风险区提取和 source_grid 输出契约。',
  },
};
const RISK_THRESHOLD_GROUPS = new Set([
  '持续性强降水',
  '短时强降水',
  '雷暴大风/下击暴流',
  '冰雹',
  '旋转风暴/超级单体潜势',
  '强对流综合风险',
]);
const RISK_THRESHOLD_GROUP_KEYS = {
  持续性强降水: 'persistent_heavy_rain',
  短时强降水: 'short_duration_heavy_rain',
  '雷暴大风/下击暴流': 'thunderstorm_gale',
  冰雹: 'hail',
  '旋转风暴/超级单体潜势': 'rotating_storm_or_supercell',
  强对流综合风险: 'severe_convection_composite',
};
const RISK_REGION_EXTRACTION_SUFFIXES = new Set([
  'score_threshold',
  'high_score_threshold',
  'min_area_grid_points',
  'max_objects',
]);
const SITUATION_EVOLUTION_LABELS = {
  subtropical_high: '副高演变',
  trough_candidate: '槽线演变',
  ridge_candidate: '脊线演变',
  low_level_jet: '低空急流演变',
  moisture_transport: '水汽输送演变',
};
const AREA_RISK_TYPES = [
  'persistent_heavy_rain',
  'short_duration_heavy_rain',
  'thunderstorm_gale',
  'hail',
  'rotating_storm_or_supercell',
  'severe_convection_composite',
];
const AREA_RISK_API_ENDPOINTS = {
  catalog: '/api/v1/diagnosis/nafp/areas',
  risks: '/api/v1/diagnosis/nafp/area-risks',
};

const {
  bboxLabel,
  buildAreaRiskQuery,
  buildDefaultTimeWindow,
  buildNafpSituationBatchRequest,
  chainTypeLabel,
  evidenceLevelLabel,
  flattenAreaRiskRows,
  formatIsoForDuty,
  formatPercent,
  formatScore,
  groupSystemsForDuty,
  riskTypeLabel,
  summarizeAreaRiskPayload,
  summarizeSituation,
  systemTypeLabel,
} = window.WeatherAdminUtils;

if ('scrollRestoration' in window.history) {
  window.history.scrollRestoration = 'manual';
}

const state = {
  result: null,
  selectedKind: null,
  selectedId: null,
  algorithmCatalog: null,
  ruleExplanations: null,
  thresholdMatrix: null,
  thresholdSelectedGroup: null,
  governanceDomain: 'weather-systems',
  dataSources: [],
  defaultDataCode: DEFAULT_DATA_CODE,
  batchResult: null,
  forecastHours: DEFAULT_FORECAST_HOURS,
  selectedForecastHours: [DEFAULT_FORECAST_HOUR],
  expandedSystemGroups: {},
  areaRiskAreas: null,
  areaRiskResult: null,
  areaRiskRows: [],
  selectedAreaRiskKey: null,
  logs: [],
};

function $(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function dataSourceLabel(item) {
  return item?.label || item?.display_name || item?.mode_name || item?.name || item?.code || DEFAULT_DATA_CODE;
}

function levelClass(level) {
  if (level === 'very_high') return 'level-high';
  if (level === 'high') return 'level-high';
  if (level === 'moderate' || level === 'medium') return 'level-moderate';
  return 'level-low';
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  const abs = Math.abs(number);
  if (abs >= 1000) return number.toFixed(0);
  if (abs >= 10) return number.toFixed(2);
  return number.toFixed(3);
}

function addLog(status, detail) {
  const now = new Date();
  state.logs.unshift({
    time: now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    status,
    detail,
  });
  state.logs = state.logs.slice(0, 8);
  renderLogs();
}

function setStatus(message, mode = '') {
  const box = $('statusMessage');
  box.className = `status-message briefing-strip${mode ? ` ${mode}` : ''}`;
  box.textContent = message;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || body?.code !== 0) {
    const msg = body?.msg || response.statusText || 'request failed';
    const detail = body?.data?.error ? `${msg}: ${body.data.error}` : msg;
    throw new Error(detail);
  }
  return body.data;
}

async function putJson(url, payload) {
  const response = await fetch(url, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || body?.code !== 0) {
    const msg = body?.msg || response.statusText || 'request failed';
    const detail = body?.data?.error ? `${msg}: ${body.data.error}` : msg;
    throw new Error(detail);
  }
  return body.data;
}

async function getJson(url) {
  const response = await fetch(url);
  const body = await response.json().catch(() => null);
  if (!response.ok || body?.code !== 0) {
    const msg = body?.msg || response.statusText || 'request failed';
    const detail = body?.data?.error ? `${msg}: ${body.data.error}` : msg;
    throw new Error(detail);
  }
  return body.data;
}

function initControls() {
  $('runTimeInput').value = buildDefaultTimeWindow().runTime;
  $('diagnosisForm').addEventListener('submit', (event) => {
    event.preventDefault();
    runDiagnosis();
  });
  $('selectCoreForecastHours')?.addEventListener('click', () => selectForecastHourRange(0, 72));
  $('selectAllForecastHours')?.addEventListener('click', () => selectForecastHourRange(0, 240));
  $('selectDefaultForecastHour')?.addEventListener('click', () => setSelectedForecastHours([DEFAULT_FORECAST_HOUR]));
  $('clearForecastHours')?.addEventListener('click', clearForecastHours);
}

function configuredForecastHours(item) {
  const hours = Array.isArray(item?.forecast_hours) && item.forecast_hours.length
    ? item.forecast_hours
    : DEFAULT_FORECAST_HOURS;
  return hours
    .map(Number)
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
}

function forecastHourLabel(hour) {
  return hour === 0 ? '起报 0h' : `+${hour}h`;
}

function selectedDataSource() {
  const code = $('dataCodeSelect')?.value || state.defaultDataCode;
  return state.dataSources.find((item) => item.code === code) || null;
}

function selectionSummary(hours) {
  if (!hours.length) return '未选择';
  if (hours.length === 1) return `已选 ${forecastHourLabel(hours[0])}`;
  const first = hours[0];
  const last = hours[hours.length - 1];
  return `已选 ${hours.length} 个：${forecastHourLabel(first)} - ${forecastHourLabel(last)}`;
}

function renderForecastHourChips() {
  const box = $('forecastHourChips');
  if (!box) return;
  const selected = new Set(state.selectedForecastHours);
  box.innerHTML = state.forecastHours.map((hour) => `
    <button class="forecast-hour-chip${selected.has(hour) ? ' active' : ''}" type="button" data-forecast-hour="${hour}" aria-pressed="${selected.has(hour) ? 'true' : 'false'}">
      ${forecastHourLabel(hour)}
    </button>
  `).join('');
  box.querySelectorAll('[data-forecast-hour]').forEach((button) => {
    button.addEventListener('click', () => toggleForecastHour(Number(button.dataset.forecastHour)));
  });
  setText('forecastSelectionSummary', selectionSummary(state.selectedForecastHours));
}

function refreshForecastHourOptions() {
  const previous = state.selectedForecastHours.length ? state.selectedForecastHours : [DEFAULT_FORECAST_HOUR];
  const source = selectedDataSource();
  const hours = configuredForecastHours(source);
  const available = new Set(hours);
  state.forecastHours = hours;
  state.selectedForecastHours = previous.filter((hour) => available.has(hour));
  if (!state.selectedForecastHours.length) {
    state.selectedForecastHours = available.has(DEFAULT_FORECAST_HOUR) ? [DEFAULT_FORECAST_HOUR] : hours.slice(0, 1);
  }
  const range = source?.forecast_hour_range;
  const hint = $('forecastHourHint');
  if (hint && range) {
    hint.textContent = `${dataSourceLabel(source)}：${range.start}-${range.end} 小时 / ${range.step} 小时间隔`;
  } else if (hint) {
    hint.textContent = '预报时效由模式配置提供';
  }
  renderForecastHourChips();
}

function selectedForecastHours() {
  return state.selectedForecastHours.slice();
}

function setSelectedForecastHours(hours) {
  const available = new Set(state.forecastHours);
  state.selectedForecastHours = [...new Set(hours.map(Number).filter((hour) => Number.isFinite(hour) && available.has(hour)))]
    .sort((a, b) => a - b);
  renderForecastHourChips();
}

function toggleForecastHour(hour) {
  const selected = new Set(state.selectedForecastHours);
  if (selected.has(hour)) {
    selected.delete(hour);
  } else {
    selected.add(hour);
  }
  setSelectedForecastHours([...selected]);
}

function selectForecastHourRange(start, end) {
  setSelectedForecastHours(state.forecastHours.filter((hour) => hour >= start && hour <= end));
}

function clearForecastHours() {
  state.selectedForecastHours = [];
  renderForecastHourChips();
}

function renderDataCodeSelect(select, options, selectedCode) {
  if (!select) return;
  select.innerHTML = options.map((item) => `
    <option value="${escapeHtml(item.code)}">${escapeHtml(dataSourceLabel(item))}</option>
  `).join('');
  select.value = options.some((item) => item.code === selectedCode)
    ? selectedCode
    : options[0]?.code || DEFAULT_DATA_CODE;
}

function renderDataSourceOptions(payload) {
  const select = $('dataCodeSelect');
  const items = (payload?.items || []).filter((item) => item?.enabled !== false);
  state.defaultDataCode = payload?.default_code || items[0]?.code || DEFAULT_DATA_CODE;
  const options = items.length
    ? items
    : [{ code: DEFAULT_DATA_CODE, label: 'ECTHIN', name: DEFAULT_DATA_CODE, model: 'EC', format: 'nc' }];
  state.dataSources = options;
  renderDataCodeSelect(select, options, state.defaultDataCode);
  renderDataCodeSelect($('areaRiskDataCodeSelect'), options, state.defaultDataCode);
  updateDataSourceHint();
  refreshForecastHourOptions();
  select?.addEventListener('change', () => {
    updateDataSourceHint();
    refreshForecastHourOptions();
  });
}

function updateDataSourceHint() {
  const hint = $('dataCodeHint');
  if (!hint) return;
  const source = selectedDataSource();
  hint.textContent = source
    ? `后台映射 ${dataSourceLabel(source)} → ${source.code}`
    : '后台映射数据编码';
}

async function loadDataSources() {
  try {
    const payload = await getJson('/api/v1/admin/data-sources');
    renderDataSourceOptions(payload);
  } catch (error) {
    renderDataSourceOptions({
      default_code: DEFAULT_DATA_CODE,
      items: [{ code: DEFAULT_DATA_CODE, label: 'ECTHIN', name: DEFAULT_DATA_CODE, model: 'EC', format: 'nc', enabled: true }],
    });
    setStatus(`模式配置加载失败，使用默认编码：${error.message}`, 'error');
  }
}

function datetimeLocalFromRunHour(runTime, forecastHour) {
  const date = new Date(normalizeRunTimeForInput(runTime));
  if (Number.isFinite(Number(forecastHour))) {
    date.setHours(date.getHours() + Number(forecastHour));
  }
  const pad = (value) => String(value).padStart(2, '0');
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join('-') + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function normalizeRunTimeForInput(value) {
  const raw = String(value || buildDefaultTimeWindow().runTime).trim().replace(' ', 'T');
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(raw)) return raw;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(raw)) return raw.slice(0, 16);
  return buildDefaultTimeWindow().runTime;
}

function renderAreaRiskTypeOptions(metadata = {}) {
  const select = $('areaRiskTypeSelect');
  if (!select) return;
  const options = AREA_RISK_TYPES.map((type) => {
    const label = metadata[type]?.label || riskTypeLabel(type);
    return `<option value="${escapeHtml(type)}">${escapeHtml(label)}</option>`;
  }).join('');
  select.innerHTML = `<option value="">全部六类风险</option>${options}`;
}

function renderAreaRiskScopeOptions(payload) {
  const select = $('areaRiskScopeSelect');
  if (!select) return;
  const cities = payload?.cities || [];
  const counties = payload?.counties || [];
  const towns = payload?.towns || [];
  const cityOptions = cities.map((item) => `
    <option value="city:${escapeHtml(item.city_code)}">${escapeHtml(item.city_name || item.city_code)} / 全部乡镇</option>
  `).join('');
  const countyOptions = counties.map((item) => `
    <option value="county:${escapeHtml(item.county_code)}">${escapeHtml(item.city_name || '')}${item.city_name ? ' / ' : ''}${escapeHtml(item.county_name || item.county_code)}</option>
  `).join('');
  const townOptions = towns.map((item) => `
    <option value="town:${escapeHtml(item.town_code)}">${escapeHtml(item.county_name || '')}${item.county_name ? ' / ' : ''}${escapeHtml(item.town_name || item.town_code)}</option>
  `).join('');
  select.innerHTML = `
    <optgroup label="地区">${cityOptions}${countyOptions}</optgroup>
    <optgroup label="乡镇">${townOptions}</optgroup>
  `;
}

async function loadAreaRiskAreas() {
  try {
    const payload = await getJson(AREA_RISK_API_ENDPOINTS.catalog);
    state.areaRiskAreas = payload;
    renderAreaRiskScopeOptions(payload);
    renderAreaRiskTypeOptions(payload.risk_metadata || {});
  } catch (error) {
    state.areaRiskAreas = null;
    renderAreaRiskTypeOptions({});
    setAreaRiskStatus(`区域目录加载失败：${error.message}`, 'error');
  }
}

function setAreaRiskStatus(message, mode = '') {
  const box = $('areaRiskStatusMessage');
  if (!box) return;
  box.className = `status-message briefing-strip${mode ? ` ${mode}` : ''}`;
  box.textContent = message;
}

function initAreaRiskControls() {
  const form = $('areaRiskForm');
  if (!form) return;
  const defaults = buildDefaultTimeWindow();
  $('areaRiskRunTimeInput').value = defaults.runTime;
  $('areaRiskStartTimeInput').value = defaults.startTime;
  $('areaRiskEndTimeInput').value = defaults.endTime;
  renderAreaRiskTypeOptions({});
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    queryAreaRisks();
  });
}

function renderAreaRiskSummary(payload) {
  const summary = summarizeAreaRiskPayload(payload);
  setText('areaRiskTownMetric', `${summary.townCount} 个`);
  setText('areaRiskHighMetric', `${summary.highRiskCount} 项`);
  setText('areaRiskMaxMetric', formatScore(summary.maxScore));
  setText('areaRiskLeadingMetric', summary.leadingRiskLabel || '-');
  setText('areaRiskRowBadge', String(summary.riskCount));
}

async function queryAreaRisks() {
  const button = $('areaRiskQueryButton');
  const url = buildAreaRiskQuery({
    dataCode: $('areaRiskDataCodeSelect')?.value || state.defaultDataCode,
    runTime: $('areaRiskRunTimeInput')?.value || buildDefaultTimeWindow().runTime,
    scopeValue: $('areaRiskScopeSelect')?.value,
    startTime: $('areaRiskStartTimeInput')?.value,
    endTime: $('areaRiskEndTimeInput')?.value,
    riskType: $('areaRiskTypeSelect')?.value || '',
  });
  button.disabled = true;
  setAreaRiskStatus('区域风险查询中');
  try {
    const payload = await getJson(url);
    state.areaRiskResult = payload;
    state.areaRiskRows = flattenAreaRiskRows(payload);
    state.selectedAreaRiskKey = state.areaRiskRows[0]?.rowKey || null;
    renderAreaRiskSummary(payload);
    renderAreaRiskRows();
    renderAreaRiskInspector();
    setAreaRiskStatus(`已返回 ${state.areaRiskRows.length} 条风险记录`, 'success');
  } catch (error) {
    setAreaRiskStatus(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

function renderAreaRiskRows() {
  const box = $('areaRiskRows');
  if (!box) return;
  const rows = state.areaRiskRows || [];
  if (!rows.length) {
    box.innerHTML = '<div class="empty-state">暂无区域风险结果</div>';
    return;
  }
  box.innerHTML = rows.map((row) => {
    const active = row.rowKey === state.selectedAreaRiskKey ? ' active' : '';
    const level = row.risk_level || row.level;
    return `
      <button class="area-risk-row${active}" type="button" data-area-risk-key="${escapeHtml(row.rowKey)}">
        <span class="area-risk-row-main">
          <strong>${escapeHtml(row.town_name || row.town_code || '-')}</strong>
          <em>${escapeHtml(row.county_name || row.city_name || '-')} · ${escapeHtml(row.label || riskTypeLabel(row.hazard_type))}</em>
        </span>
        <span class="area-risk-row-time">${escapeHtml(formatIsoForDuty(row.valid_time))}<em>+${escapeHtml(row.forecast_hour)}h</em></span>
        <span class="area-risk-row-score">
          <span class="level-pill ${levelClass(level)}">${escapeHtml(evidenceLevelLabel(level))}</span>
          <strong>${escapeHtml(formatScore(row.score))}</strong>
        </span>
      </button>
    `;
  }).join('');
  box.querySelectorAll('[data-area-risk-key]').forEach((button) => {
    button.addEventListener('click', () => {
      state.selectedAreaRiskKey = button.dataset.areaRiskKey;
      renderAreaRiskRows();
      renderAreaRiskInspector();
    });
  });
}

function detailLine(label, value) {
  return `<div class="detail-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? '-')}</strong></div>`;
}

function renderAreaRiskInspector() {
  const box = $('areaRiskInspectorBody');
  if (!box) return;
  const row = (state.areaRiskRows || []).find((item) => item.rowKey === state.selectedAreaRiskKey);
  if (!row) {
    box.innerHTML = '<div class="empty-state">选择一条乡镇风险</div>';
    return;
  }
  const metadata = row.metadata || state.areaRiskResult?.risk_metadata?.[row.hazard_type] || {};
  const evidence = row.evidence_chain || {};
  const factors = evidence.dominant_factors || [];
  const maxSample = evidence.max_sample || {};
  box.innerHTML = `
    <section class="area-risk-detail-block">
      <div class="area-risk-detail-title">
        <span class="level-pill ${levelClass(row.risk_level || row.level)}">${escapeHtml(evidenceLevelLabel(row.risk_level || row.level))}</span>
        <div>
          <strong>${escapeHtml(row.label || riskTypeLabel(row.hazard_type))}</strong>
          <em>${escapeHtml(row.town_name || '-')} · ${escapeHtml(formatIsoForDuty(row.valid_time))}</em>
        </div>
      </div>
      <p>${escapeHtml(metadata.description || '')}</p>
      <p class="muted-copy">${escapeHtml(metadata.evidence_summary || '')}</p>
    </section>
    <div class="detail-grid compact-detail-grid">
      ${detailLine('source_grid', row.source_grid)}
      ${detailLine('评分统计', `${formatScore(row.max_score ?? row.score)} / ${formatScore(row.mean_score)} / ${formatScore(row.p90_score)}`)}
      ${detailLine('样本数量', `${row.sample_count || 0}/${row.station_count || 0}`)}
      ${detailLine('最大样本', maxSample.station_name || maxSample.display_name || '-')}
    </div>
    <section class="evidence-list area-risk-factor-list" aria-label="主导因子">
      ${factors.length ? factors.map((factor) => `
        <article class="evidence-item">
          <strong>${escapeHtml(factor.label || factor.factor)}</strong>
          <span>${escapeHtml(factor.field || factor.factor)} · 权重 ${escapeHtml(formatScore(factor.weight))}</span>
          <p>平均贡献 ${escapeHtml(formatScore(factor.mean_contribution))}，最大贡献 ${escapeHtml(formatScore(factor.max_contribution))}</p>
        </article>
      `).join('') : '<div class="empty-state">暂无主导因子</div>'}
    </section>
  `;
}

function initAlgorithmControls() {
  $('saveThresholdMatrix')?.addEventListener('click', saveThresholdMatrix);
}

function viewFromHash() {
  const hash = window.location.hash ? window.location.hash.slice(1) : '';
  if (!hash) return DEFAULT_VIEW;
  if (hash.startsWith('view-')) return hash.slice(5);
  return hash;
}

function viewFromLocation() {
  const params = new URLSearchParams(window.location.search);
  return params.get('view') || viewFromHash();
}

function updateViewUrl(view) {
  if (!window.history?.replaceState) return;
  const url = new URL(window.location.href);
  url.searchParams.delete('view');
  url.hash = '';
  window.history.replaceState(null, '', `${url.pathname}${url.search}`);
}

function resetMainStageScroll() {
  const mainStage = document.querySelector('.main-stage');
  if (!mainStage) return;
  const reset = () => {
    const previousOverflow = mainStage.style.overflow;
    mainStage.style.overflow = 'hidden';
    mainStage.scrollTop = 0;
    mainStage.scrollLeft = 0;
    mainStage.style.overflow = previousOverflow;
    mainStage.scrollTop = 0;
    mainStage.scrollLeft = 0;
  };
  reset();
  if (window.requestAnimationFrame) window.requestAnimationFrame(reset);
  window.setTimeout?.(reset, 80);
}

function selectView(view, { updateHash = true } = {}) {
  const target = document.querySelector(`[data-view-panel="${view}"]`)
    ? view
    : DEFAULT_VIEW;
  view = target;
  document.querySelectorAll('.nav-item[data-view]').forEach((item) => {
    const active = item.dataset.view === view;
    item.classList.toggle('active', active);
    if (active) {
      item.setAttribute('aria-current', 'page');
    } else {
      item.removeAttribute('aria-current');
    }
  });
  document.querySelector('.workspace-ribbon')?.setAttribute('data-active-view', view);
  document.querySelectorAll('.module-panel').forEach((panel) => {
    const active = panel.dataset.viewPanel === view;
    panel.classList.toggle('active', active);
    panel.hidden = panel.dataset.viewPanel !== view;
  });
  if (updateHash) updateViewUrl(view);
  resetMainStageScroll();
}

function setupNavigation() {
  const links = Array.from(document.querySelectorAll('.nav-item'));
  links.forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      selectView(link.dataset.view);
    });
  });
  document.querySelectorAll('[data-overview-link]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      selectView(link.dataset.overviewLink);
    });
  });
  const params = new URLSearchParams(window.location.search);
  const initialHash = window.location.hash ? window.location.hash.slice(1) : '';
  const initial = viewFromLocation();
  const shouldNormalizeUrl = Boolean(initialHash || params.has('view'));
  selectView(initial, { updateHash: shouldNormalizeUrl });
}

function selectGovernanceTab(tab) {
  const target = document.querySelector(`[data-governance-panel="${tab}"]`)
    ? tab
    : 'algorithms';
  document.querySelectorAll('[data-governance-tab]').forEach((button) => {
    const active = button.dataset.governanceTab === target;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-governance-panel]').forEach((panel) => {
    const active = panel.dataset.governancePanel === target;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

function governanceDomainMeta(domain = state.governanceDomain) {
  return GOVERNANCE_DOMAINS[domain] || GOVERNANCE_DOMAINS['weather-systems'];
}

function renderGovernanceDomainChrome() {
  const meta = governanceDomainMeta();
  document.querySelectorAll('[data-governance-domain]').forEach((button) => {
    const active = button.dataset.governanceDomain === state.governanceDomain;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  setText('governanceDomainSummary', meta.summary);
  setText('algorithmDomainBadge', meta.label);
  setText('ruleExplanationDomainBadge', meta.label);
}

function selectGovernanceDomain(domain) {
  const target = GOVERNANCE_DOMAINS[domain] ? domain : 'weather-systems';
  if (state.governanceDomain === target) {
    renderGovernanceDomainChrome();
    return;
  }
  syncThresholdDraftFromDom();
  state.governanceDomain = target;
  state.thresholdSelectedGroup = null;
  renderGovernanceDomainChrome();
  renderAlgorithmLibrary(state.algorithmCatalog);
  renderRuleExplanations(state.ruleExplanations);
  renderThresholdMatrix(state.thresholdMatrix);
}

function setupGovernanceDomains() {
  document.querySelectorAll('[data-governance-domain]').forEach((button) => {
    button.addEventListener('click', () => selectGovernanceDomain(button.dataset.governanceDomain));
  });
  renderGovernanceDomainChrome();
}

function setupGovernanceTabs() {
  document.querySelectorAll('[data-governance-tab]').forEach((button) => {
    button.addEventListener('click', () => selectGovernanceTab(button.dataset.governanceTab));
  });
  selectGovernanceTab('algorithms');
}

function validatePayload(payload) {
  if (!payload.data_code) return '数据编码不能为空';
  if (!payload.run_time) return '起报时间不能为空';
  if (!payload.forecast_hours?.length) return '至少选择一个预报时效';
  if (payload.forecast_hours.some((hour) => !Number.isFinite(hour))) return '时效必须是数字';
  return '';
}

function renderSituationEvolution(batch) {
  const evolution = batch?.situation_evolution;
  const evolutionItems = Array.isArray(evolution?.items) ? evolution.items : [];
  const fallbackItems = batch?.subtropical_high_trend?.trend_summary
    ? [batch.subtropical_high_trend]
    : [];
  const items = evolutionItems.length ? evolutionItems : fallbackItems;
  if (!items.length) return '';
  return `
    <div class="batch-trend-summary situation-evolution-panel">
      <div>
        <span class="panel-kicker">天气形势演变</span>
        ${evolution?.trend_summary ? `<strong>${escapeHtml(evolution.trend_summary)}</strong>` : ''}
      </div>
      <div class="situation-evolution-list">
        ${items.map((item) => `
          <article class="situation-evolution-item">
            <span>${escapeHtml(SITUATION_EVOLUTION_LABELS[item.system_type] || item.label || item.system_type || '系统演变')}</span>
            <strong>${escapeHtml(item.trend_summary || '样本不足')}</strong>
          </article>
        `).join('')}
      </div>
    </div>
  `;
}

function renderBatchSummary(batch) {
  const box = $('batchSummary');
  if (!box) return;
  if (!batch) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  const results = batch.results || [];
  const failed = batch.failed || [];
  const preview = results.slice(0, 12);
  box.hidden = false;
  box.innerHTML = `
    <div>
      <span class="panel-kicker">批量诊断</span>
      <strong>${results.length} 个成功 / ${failed.length} 个失败</strong>
    </div>
    <div class="batch-hour-rail">
      ${preview.map((item) => `<span class="batch-hour-chip">+${escapeHtml(item.forecast_hour)}h</span>`).join('')}
      ${results.length > preview.length ? `<span class="batch-hour-chip muted">+${results.length - preview.length} 个</span>` : ''}
      ${failed.map((item) => `<span class="batch-hour-chip failed">+${escapeHtml(item.forecast_hour)}h 失败</span>`).join('')}
    </div>
    ${renderSituationEvolution(batch)}
  `;
}

async function runDiagnosis() {
  const payload = buildNafpSituationBatchRequest(
    $('dataCodeSelect').value,
    $('runTimeInput').value,
    selectedForecastHours(),
  );
  const validation = validatePayload(payload);
  if (validation) {
    setStatus(validation, 'error');
    return;
  }

  const button = $('runButton');
  button.disabled = true;
  setStatus('诊断生成中');
  renderBatchSummary(null);
  addLog('提交诊断', `${payload.run_time} · ${payload.forecast_hours.join('/')}h`);
  try {
    const batch = await postJson('/api/v1/diagnosis/nafp/situations', payload);
    const result = batch.results?.[0];
    if (!result) {
      throw new Error(batch.failed?.[0]?.error || batch.failed?.[0]?.msg || '没有生成成功的诊断结果');
    }
    state.batchResult = batch;
    state.result = result;
    state.expandedSystemGroups = {};
    state.selectedKind = result.risk_diagnoses?.length ? 'risk' : 'system';
    state.selectedId = result.risk_diagnoses?.[0]?.risk_id || result.systems?.[0]?.id || null;
    renderResult();
    renderBatchSummary(batch);
    setStatus(`${buildDutySummary(result)}；批量成功 ${batch.result_count} 个，失败 ${batch.failed_count} 个`, 'success');
    addLog('诊断完成', `${batch.result_count} 个时效成功，${batch.failed_count} 个失败`);
  } catch (error) {
    setStatus(error.message, 'error');
    addLog('诊断失败', error.message);
  } finally {
    button.disabled = false;
  }
}

function renderResult() {
  const result = state.result;
  if (!result) return;
  const summary = summarizeSituation(result);
  setText('validTimeMetric', formatIsoForDuty(result.valid_time));
  setText('completenessMetric', formatPercent(summary.completeness));
  setText('systemMetric', `${summary.systemCount} 个`);
  setText('riskMetric', `${summary.highRiskCount} 高 / ${summary.moderateRiskCount} 中`);
  setText('systemCountBadge', String(summary.systemCount));
  setText('chainCountBadge', String(result.risk_diagnoses?.length || 0));
  setText('missingBadge', `${summary.missingCount} 缺测`);
  renderSystems(result.systems || []);
  renderRisks(result.risk_diagnoses || []);
  renderFieldMatrix(result);
  renderDiagnostics(result.diagnostics || {});
  renderInspector();
}

function selectItem(kind, id) {
  state.selectedKind = kind;
  state.selectedId = id;
  renderSystems(state.result?.systems || []);
  renderRisks(state.result?.risk_diagnoses || []);
  renderInspector();
}

function renderSystems(systems) {
  const body = $('systemsGroupList');
  if (!systems.length) {
    body.innerHTML = '<div class="empty-state">暂无诊断结果</div>';
    return;
  }
  const groups = groupSystemsForDuty(systems, 4);
  if (!groups.length) {
    body.innerHTML = '<div class="empty-state">暂无主要天气系统</div>';
    return;
  }
  body.innerHTML = groups.map((group) => {
    const selectedInGroup = group.items.some((system) => system.id === state.selectedId && state.selectedKind === 'system');
    const expanded = Boolean(state.expandedSystemGroups[group.type] || selectedInGroup);
    const visibleItems = expanded ? group.items : group.previewItems;
    const groupActive = selectedInGroup ? ' active-group' : '';
    const levelText = group.levels.length ? group.levels.join(' / ') : '-';
    const toggle = group.remaining > 0
      ? `<button class="system-group-toggle" type="button" data-group-toggle="${escapeHtml(group.type)}">${expanded ? '收起' : `展开 ${group.remaining} 个`}</button>`
      : '';
    return `
      <section class="system-group${groupActive}" aria-label="${escapeHtml(group.label)}">
        <header class="system-group-head">
          <div>
            <span class="type-pill">${escapeHtml(group.label)}</span>
            <strong>${group.count} 个对象</strong>
          </div>
          <div class="system-group-meta">
            <span>${escapeHtml(levelText)}</span>
            <span>${formatPercent(group.averageConfidence * 100)}</span>
            ${toggle}
          </div>
        </header>
        <div class="system-object-stack">
          ${visibleItems.map((system) => {
            const active = state.selectedKind === 'system' && state.selectedId === system.id ? ' active' : '';
            return `
              <button class="system-object-row${active}" type="button" data-kind="system" data-id="${escapeHtml(system.id)}">
                <span>
                  <strong>${escapeHtml(system.name || systemTypeLabel(system.type))}</strong>
                  <em>${escapeHtml(bboxLabel(system.geometry))}</em>
                </span>
                <span class="system-object-meta">
                  <span>${escapeHtml(system.level || '-')}</span>
                  <span>${formatPercent((Number(system.confidence) || 0) * 100)}</span>
                </span>
              </button>
            `;
          }).join('')}
        </div>
      </section>
    `;
  }).join('');
  body.querySelectorAll('[data-group-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      const type = button.dataset.groupToggle;
      state.expandedSystemGroups[type] = !state.expandedSystemGroups[type];
      renderSystems(state.result?.systems || []);
    });
  });
  body.querySelectorAll('[data-id]').forEach((row) => {
    row.addEventListener('click', () => selectItem(row.dataset.kind, row.dataset.id));
  });
}

function renderRisks(risks) {
  const box = $('chainList');
  if (!risks.length) {
    box.innerHTML = '<div class="empty-state">暂无风险诊断</div>';
    return;
  }
  box.innerHTML = risks.map((risk) => {
    const id = risk.risk_id || risk.hazard_type;
    const level = risk.risk_level || risk.level;
    const active = state.selectedKind === 'risk' && state.selectedId === id ? ' active' : '';
    const evidenceCount = risk.dominant_evidence?.length || 0;
    return `
      <button class="chain-row${active}" type="button" data-id="${escapeHtml(id)}">
        <span>
          <span class="chain-row-title">
            <span class="level-pill ${levelClass(level)}">${evidenceLevelLabel(level)}</span>
            ${escapeHtml(risk.label || riskTypeLabel(risk.hazard_type))}
          </span>
          <span class="chain-row-meta">${escapeHtml(risk.source_grid || '-')} · ${evidenceCount} 个主导因子</span>
        </span>
        <span class="score-value">${formatScore(risk.score)}</span>
      </button>
    `;
  }).join('');
  box.querySelectorAll('button[data-id]').forEach((button) => {
    button.addEventListener('click', () => selectItem('risk', button.dataset.id));
  });
}

function renderFieldMatrix(result) {
  const missing = new Set((result.missing_fields || []).map((item) => item.field));
  $('fieldMatrix').innerHTML = FIELD_ORDER.map((field) => {
    const isMissing = missing.has(field);
    return `
      <span class="field-pill${isMissing ? ' missing' : ''}">
        <span>${escapeHtml(field)}</span>
        <span>${isMissing ? '缺测' : '可用'}</span>
      </span>
    `;
  }).join('');
}

function renderDiagnostics(diagnostics) {
  const rows = Object.entries(diagnostics)
    .filter(([, stats]) => stats && typeof stats === 'object')
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, stats]) => `
      <tr>
        <td>${escapeHtml(name)}</td>
        <td class="number-col">${formatNumber(stats.min)}</td>
        <td class="number-col">${formatNumber(stats.mean)}</td>
        <td class="number-col">${formatNumber(stats.max)}</td>
        <td class="number-col">${formatNumber(stats.p90)}</td>
      </tr>
    `);
  $('diagnosticsTableBody').innerHTML = rows.length
    ? rows.join('')
    : '<tr><td colspan="5" class="empty-cell">暂无统计</td></tr>';
}

function governanceDomainItems(catalog) {
  const out = [];
  (catalog?.algorithms || []).forEach((algorithm) => {
    if (state.governanceDomain === 'weather-systems') {
      (algorithm.systems || [])
        .filter((system) => system.governance_domain === 'weather-systems')
        .forEach((system) => {
          out.push({
            id: system.system_id,
            name: system.name,
            model: algorithm.model,
            status: algorithm.status,
            kind: '天气系统',
            method: system.method,
            inputs: (system.fields || []).map((field) => ({ field, required: true })),
            inputLabel: `${(system.fields || []).length} 个输入场`,
            outputs: ['systems', 'geometry', 'evidence'],
          });
        });
    }
    if (state.governanceDomain === 'risk-diagnosis') {
      (algorithm.evidence_chains || [])
        .filter((chain) => chain.governance_domain === 'risk-diagnosis')
        .forEach((chain) => {
          out.push({
            id: chain.chain_id,
            name: chain.name,
            model: algorithm.model,
            status: algorithm.status,
            kind: '风险诊断',
            method: chain.method,
            inputs: [],
            inputLabel: '格点评分 / 风险区提取',
            outputs: ['source_grid', 'dominant_evidence', 'supporting_systems'],
          });
        });
    }
  });
  return out;
}

function algorithmMetaItems(item, inputs) {
  return [
    item.id || '-',
    item.inputLabel || `${inputs.filter((input) => input.required).length} 个输入场`,
  ].filter(Boolean);
}

function algorithmOutputItems(item, inputs) {
  if (inputs.length) {
    return inputs.map((input) => ({
      label: input.field,
      required: input.required,
    }));
  }
  return (item.outputs || []).map((label) => ({ label, required: false }));
}

function renderAlgorithmLibrary(catalog) {
  renderGovernanceDomainChrome();
  const items = governanceDomainItems(catalog);
  setText('algorithmCountBadge', String(items.length));
  const box = $('algorithmLibrary');
  if (!box) return;
  if (!items.length) {
    box.innerHTML = '<div class="empty-state">暂无算法资产</div>';
    return;
  }
  box.innerHTML = items.map((item) => {
    const inputs = item.inputs || [];
    const metaItems = algorithmMetaItems(item, inputs);
    const outputItems = algorithmOutputItems(item, inputs);
    return `
      <article class="algorithm-card">
        <header>
          <div>
            <span class="panel-kicker">${escapeHtml(item.model || '-')} · ${escapeHtml(item.kind)}</span>
            <h4>${escapeHtml(item.name || item.id)}</h4>
          </div>
          <span class="type-pill">${escapeHtml(item.status || '-')}</span>
        </header>
        <div class="algorithm-meta">
          ${metaItems.map((value) => `<span>${escapeHtml(value)}</span>`).join('')}
        </div>
        <p class="algorithm-method-text">${escapeHtml(item.method || '-')}</p>
        <div class="${inputs.length ? 'input-rail' : 'algorithm-contract-rail'}" aria-label="${inputs.length ? '输入场' : '输出契约'}">
          ${inputs.length ? outputItems.map((input) => `
            <span class="${input.required ? 'required' : ''}">
              ${escapeHtml(input.label)}
            </span>
          `).join('') : `
            <strong>输出</strong>
            ${outputItems.map((item) => `<span>${escapeHtml(item.label)}</span>`).join('')}
          `}
        </div>
      </article>
    `;
  }).join('');
}

function ruleList(items) {
  const values = (items || []).filter(Boolean);
  if (!values.length) return '<ul><li>-</li></ul>';
  return `<ul>${values.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
}

function renderRuleComposition(composition) {
  if (!composition) return '';
  const channels = composition.channels || [];
  return `
    <section class="rule-composition" aria-label="合成方式">
      <div class="rule-composition-head">
        <strong>合成方式</strong>
        <span>${escapeHtml(composition.label || composition.mode || '-')}</span>
      </div>
      <p>${escapeHtml(composition.formula || composition.description || '-')}</p>
      ${composition.description ? `<em>${escapeHtml(composition.description)}</em>` : ''}
      <div class="rule-composition-channels">
        ${channels.map((channel) => `
          <article>
            <strong>${escapeHtml(channel.label || channel.channel_id || '-')}</strong>
            <span>${escapeHtml(channel.field || '-')}</span>
            <p>${escapeHtml(channel.basis || '')}</p>
          </article>
        `).join('')}
      </div>
    </section>
  `;
}

function thresholdEntryText(entry) {
  if (!entry) return '-';
  const value = entry.threshold === null || entry.threshold === undefined ? '-' : formatMatrixValue(entry.threshold);
  const unit = entry.unit ? ` ${entry.unit}` : '';
  const weight = entry.weight === null || entry.weight === undefined ? '' : ` · w=${formatMatrixValue(entry.weight)}`;
  const operator = thresholdOperatorLabel(entry.operator);
  if (value === '-') return `${entry.field || entry.entry_id}: ${operator}${weight}`;
  return `${entry.field || entry.entry_id}: ${operator} ${value}${unit}${weight}`;
}

function ruleDomain(section) {
  return section?.governance_domain || (section?.category === '天气系统' ? 'weather-systems' : 'risk-diagnosis');
}

function renderRuleExplanations(payload) {
  renderGovernanceDomainChrome();
  const sections = (payload?.sections || []).filter((section) => ruleDomain(section) === state.governanceDomain);
  setText('ruleExplanationBadge', String(sections.length));
  const box = $('ruleExplanationPanel');
  if (!box) return;
  if (!sections.length) {
    box.innerHTML = '<div class="empty-state">暂无诊断规则</div>';
    return;
  }
  box.innerHTML = sections.map((section) => {
    const inputs = section.inputs || [];
    const thresholds = section.threshold_details || [];
    const missing = section.missing_threshold_entries || [];
    return `
      <article class="rule-explanation-card">
        <header>
          <div>
            <span class="panel-kicker">${escapeHtml(section.category || '-')}</span>
            <h4>${escapeHtml(section.title || section.rule_id)}</h4>
          </div>
          <span class="type-pill">${escapeHtml(section.rule_id)}</span>
        </header>
        <p class="rule-purpose">${escapeHtml(section.purpose || '-')}</p>
        <div class="rule-mini-grid">
          <section>
            <strong>判据</strong>
            ${ruleList(section.basis)}
          </section>
          <section>
            <strong>算法</strong>
            ${ruleList(section.method)}
          </section>
        </div>
        ${renderRuleComposition(section.composition)}
        <div class="rule-input-rail">
          ${inputs.map((item) => `
            <span class="${item.required ? 'required' : ''}">
              ${escapeHtml(item.field)}<em>${escapeHtml(item.role || '')}</em>
            </span>
          `).join('')}
        </div>
        <div class="rule-threshold-rail" aria-label="阈值条目">
          ${thresholds.map((entry) => `
            <span class="rule-threshold-chip" title="${escapeHtml(entry.entry_id)}">
              <strong>${escapeHtml(entry.signal || entry.entry_id)}</strong>
              <em>${escapeHtml(thresholdEntryText(entry))}</em>
            </span>
          `).join('')}
          ${missing.map((entryId) => `<span class="rule-threshold-chip missing">${escapeHtml(entryId)}</span>`).join('')}
        </div>
        <details class="rule-contract">
          <summary>输出与证据契约</summary>
          <div>
            ${ruleList(section.outputs)}
            ${ruleList(section.evidence_contract)}
          </div>
        </details>
      </article>
    `;
  }).join('');
}

function setThresholdMatrixBadge(matrix) {
  const badge = $('thresholdMatrixBadge');
  if (!badge) return;
  badge.textContent = matrix?.status || 'default';
}

function formatMatrixValue(value) {
  if (value === null || value === undefined || value === '') return '';
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  return String(Number(number.toFixed(4)));
}

function thresholdGroupLabel(group) {
  const labels = {
    _pressure_center_systems: '高低压系统',
    _trough_ridge_systems: '槽脊线系统',
    _front_candidate_systems: '锋面候选',
    天气系统: '天气系统',
  };
  if (RISK_THRESHOLD_GROUPS.has(group)) return group;
  return labels[group] || String(group || '未分组').replace(/^_/, '');
}

function thresholdGroupDomain(group) {
  const value = String(group || '');
  if (value === '天气系统' || value.endsWith('_systems')) return 'weather-systems';
  if (RISK_THRESHOLD_GROUPS.has(value)) return 'risk-diagnosis';
  return 'supporting-diagnosis';
}

function thresholdGroupKeyLabel(group) {
  const labels = {
    天气系统: 'weather_system',
  };
  if (RISK_THRESHOLD_GROUP_KEYS[group]) return RISK_THRESHOLD_GROUP_KEYS[group];
  return labels[group] || String(group || 'ungrouped').replace(/^_/, '');
}

function thresholdGroups(version) {
  const groups = new Map();
  (version?.entries || [])
    .filter((entry) => thresholdGroupDomain(entry.group) === state.governanceDomain)
    .forEach((entry) => {
    const group = entry.group || 'ungrouped';
    if (!groups.has(group)) {
      groups.set(group, {
        group,
        label: thresholdGroupLabel(group),
        entries: [],
        enabledCount: 0,
      });
    }
    const bucket = groups.get(group);
    bucket.entries.push(entry);
    if (entry.enabled) bucket.enabledCount += 1;
  });
  return Array.from(groups.values());
}

function selectedThresholdEntries(version) {
  const entries = version?.entries || [];
  if (!entries.length) return [];
  const groups = thresholdGroups(version);
  const selected = state.thresholdSelectedGroup || groups[0]?.group;
  state.thresholdSelectedGroup = selected;
  return entries.filter((entry) => (entry.group || 'ungrouped') === selected);
}

function thresholdEntrySection(entry) {
  if (thresholdGroupDomain(entry?.group) !== 'risk-diagnosis') return 'default';
  const suffix = String(entry?.entry_id || '').split('.').pop();
  if (RISK_REGION_EXTRACTION_SUFFIXES.has(suffix)) return 'risk-region';
  return 'risk-factor';
}

function thresholdSectionLabel(section) {
  if (section === 'risk-factor') return '格点评分因子';
  if (section === 'risk-region') return '风险区生成规则';
  return '';
}

function thresholdSectionHint(section) {
  if (section === 'risk-factor') return '参考数值预报物理量，把每个格点换算成 0-1 风险贡献';
  if (section === 'risk-region') return '从 source_grid 中提取可展示、可排序的风险区对象';
  return '';
}

function thresholdEntrySections(entries) {
  if (!entries.some((entry) => thresholdEntrySection(entry) !== 'default')) {
    return [{ section: 'default', entries }];
  }
  return ['risk-factor', 'risk-region']
    .map((section) => ({
      section,
      entries: entries.filter((entry) => thresholdEntrySection(entry) === section),
    }))
    .filter((item) => item.entries.length);
}

function renderThresholdGroups(version) {
  const box = $('thresholdGroupList');
  if (!box) return;
  const groups = thresholdGroups(version);
  if (!groups.length) {
    box.innerHTML = '<div class="empty-state">暂无组别</div>';
    return;
  }
  if (!state.thresholdSelectedGroup || !groups.some((item) => item.group === state.thresholdSelectedGroup)) {
    state.thresholdSelectedGroup = groups[0].group;
  }
  box.innerHTML = groups.map((item) => `
    <button class="threshold-group-button${item.group === state.thresholdSelectedGroup ? ' active' : ''}" type="button" data-threshold-group="${escapeHtml(item.group)}">
      <span>
        <strong>${escapeHtml(item.label)}</strong>
        <em>${escapeHtml(thresholdGroupKeyLabel(item.group))}</em>
      </span>
      <span class="threshold-group-count">${item.enabledCount}/${item.entries.length}</span>
    </button>
  `).join('');
  box.querySelectorAll('[data-threshold-group]').forEach((button) => {
    button.addEventListener('click', () => selectThresholdGroup(button.dataset.thresholdGroup));
  });
}

function renderThresholdGroupHeader(entries) {
  const group = state.thresholdSelectedGroup;
  setText('thresholdGroupTitle', thresholdGroupLabel(group));
  const sections = thresholdEntrySections(entries).filter((item) => item.section !== 'default');
  const detail = sections.length
    ? ` · ${sections.map((item) => `${thresholdSectionLabel(item.section)} ${item.entries.length}`).join(' / ')}`
    : '';
  setText('thresholdGroupMeta', `${entries.length} 项${detail}`);
}

function selectThresholdGroup(group) {
  syncThresholdDraftFromDom();
  state.thresholdSelectedGroup = group;
  renderThresholdMatrix(state.thresholdMatrix);
}

function renderThresholdMatrix(version) {
  const body = $('thresholdMatrixBody');
  if (!body) return;
  if (!version?.entries?.length) {
    renderThresholdGroups(version);
    renderThresholdGroupHeader([]);
    body.innerHTML = '<tr><td colspan="6" class="empty-cell">暂无阈值矩阵</td></tr>';
    return;
  }
  setThresholdMatrixBadge(version);
  renderThresholdGroups(version);
  const entries = selectedThresholdEntries(version);
  renderThresholdGroupHeader(entries);
  body.innerHTML = thresholdEntrySections(entries).map(renderThresholdSection).join('');
  body.querySelectorAll('.matrix-input, .matrix-toggle').forEach((input) => {
    input.addEventListener('input', () => updateThresholdDraftEntry(input.closest('.threshold-row')));
    input.addEventListener('change', () => updateThresholdDraftEntry(input.closest('.threshold-row')));
  });
}

function renderThresholdSection(section) {
  const rows = section.entries.map(renderThresholdRow).join('');
  if (section.section === 'default') return rows;
  return `
    <tr class="threshold-section-row" data-threshold-section="${escapeHtml(section.section)}">
      <td colspan="6">
        <div class="threshold-section-title">
          <strong>${escapeHtml(thresholdSectionLabel(section.section))}</strong>
          <span>${escapeHtml(thresholdSectionHint(section.section))} · ${section.entries.length} 项</span>
        </div>
      </td>
    </tr>
    ${rows}
  `;
}

function thresholdStatisticLabel(statistic) {
  const labels = {
    factor_component_score: '物理量评分',
    factor_component_weight: '分项权重',
    factor_score: '因子评分',
    factor_weight: '因子权重',
    score: '风险分',
    count: '连续格点数',
    rank: '输出数量',
    point: '格点值',
    max: '区域最大值',
    min: '区域最小值',
    mean: '区域平均值',
  };
  return labels[statistic] || statistic || '-';
}

function thresholdOperatorLabel(operator) {
  const labels = {
    ramp: '越高越有利',
    negative_ratio: '越低越有利',
    triangular: '区间最优',
    weight: '贡献权重',
    '>=': '不小于',
    '<=': '不大于',
    '>': '大于',
    '<': '小于',
    ratio: '按比例增强',
    abs_negative_ratio: '绝对值越小越有利',
  };
  return labels[operator] || operator || '-';
}

function thresholdModeLabel(entry) {
  return `${thresholdStatisticLabel(entry.statistic)} · ${thresholdOperatorLabel(entry.operator)}`;
}

function thresholdInputDisabled(entry, field) {
  if (field === 'threshold') return entry.threshold === null || entry.threshold === undefined;
  if (field === 'scale') return entry.scale === null || entry.scale === undefined || thresholdEntrySection(entry) === 'risk-region';
  if (field === 'weight') return entry.weight === null || entry.weight === undefined || thresholdEntrySection(entry) === 'risk-region';
  return false;
}

function thresholdInputAttrs(entry, field) {
  const disabled = thresholdInputDisabled(entry, field);
  return disabled ? ' placeholder="-" disabled aria-label="不适用"' : '';
}

function renderThresholdRow(entry) {
  return `
    <tr class="threshold-row" data-entry-id="${escapeHtml(entry.entry_id)}">
      <td>
        <strong>${escapeHtml(entry.field || '-')}</strong>
        <span>${escapeHtml(entry.source || '-')}</span>
      </td>
      <td>
        <strong>${escapeHtml(entry.signal || entry.entry_id)}</strong>
        <span>${escapeHtml(thresholdModeLabel(entry))}</span>
      </td>
      <td class="number-col">
        <input class="matrix-input" data-matrix-field="threshold" type="number" step="0.01" value="${formatMatrixValue(entry.threshold)}"${thresholdInputAttrs(entry, 'threshold')} />
      </td>
      <td class="number-col">
        <input class="matrix-input" data-matrix-field="scale" type="number" step="0.01" value="${formatMatrixValue(entry.scale)}"${thresholdInputAttrs(entry, 'scale')} />
      </td>
      <td class="number-col">
        <input class="matrix-input" data-matrix-field="weight" type="number" min="0" max="1" step="0.01" value="${formatMatrixValue(entry.weight)}"${thresholdInputAttrs(entry, 'weight')} />
      </td>
      <td>
        <input class="matrix-toggle" data-matrix-field="enabled" type="checkbox"${entry.enabled ? ' checked' : ''} />
      </td>
    </tr>
  `;
}

function readMatrixNumber(row, field) {
  const input = row.querySelector(`[data-matrix-field="${field}"]`);
  if (!input || input.value.trim() === '') return null;
  const value = Number(input.value);
  return Number.isFinite(value) ? value : null;
}

function updateThresholdDraftEntry(row) {
  if (!row || !state.thresholdMatrix?.entries) return;
  const entryId = row.dataset.entryId;
  const entry = state.thresholdMatrix.entries.find((item) => item.entry_id === entryId);
  if (!entry) return;
  entry.threshold = readMatrixNumber(row, 'threshold');
  entry.scale = readMatrixNumber(row, 'scale');
  entry.weight = readMatrixNumber(row, 'weight');
  entry.enabled = Boolean(row.querySelector('[data-matrix-field="enabled"]')?.checked);
  renderThresholdGroups(state.thresholdMatrix);
}

function syncThresholdDraftFromDom() {
  document.querySelectorAll('.threshold-row').forEach((row) => updateThresholdDraftEntry(row));
}

function collectThresholdEntries() {
  syncThresholdDraftFromDom();
  const matrix = state.thresholdMatrix;
  return (matrix?.entries || []).map((entry) => ({ ...entry }));
}

async function loadAlgorithmManagement() {
  try {
    const [catalog, explanations] = await Promise.all([
      getJson('/api/v1/admin/algorithms/catalog'),
      getJson('/api/v1/admin/algorithms/rule-explanations'),
    ]);
    state.algorithmCatalog = catalog;
    state.ruleExplanations = explanations;
    renderAlgorithmLibrary(catalog);
    renderRuleExplanations(explanations);
    const matrix = catalog.threshold_matrix || await getJson('/api/v1/admin/algorithms/threshold-matrix');
    state.thresholdMatrix = matrix;
    state.thresholdSelectedGroup = null;
    renderThresholdMatrix(matrix);
  } catch (error) {
    $('algorithmLibrary').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    $('ruleExplanationPanel').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    $('thresholdGroupList').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    setText('thresholdGroupTitle', '加载失败');
    setText('thresholdGroupMeta', '0 项');
    $('thresholdMatrixBody').innerHTML = `<tr><td colspan="6" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function saveThresholdMatrix() {
  if (!state.thresholdMatrix) return;
  const button = $('saveThresholdMatrix');
  button.disabled = true;
  const payload = {
    algorithm_id: state.thresholdMatrix.algorithm_id,
    remark: '后台保存默认阈值矩阵',
    entries: collectThresholdEntries(),
    level_thresholds: state.thresholdMatrix.level_thresholds || [],
  };
  try {
    const saved = await putJson('/api/v1/admin/algorithms/threshold-matrix', payload);
    state.thresholdMatrix = saved;
    renderThresholdMatrix(saved);
    setStatus(`默认阈值矩阵已保存：${saved.entries.length} 项`, 'success');
    addLog('保存默认矩阵', `${saved.matrix_id} · ${saved.entries.length} 项`);
  } catch (error) {
    setStatus(error.message, 'error');
    addLog('阈值保存失败', error.message);
  } finally {
    button.disabled = false;
  }
}

function buildDutySummary(result) {
  const systems = result.systems || [];
  const risks = result.risk_diagnoses || [];
  const systemCounts = systems.reduce((acc, system) => {
    const label = systemTypeLabel(system.type);
    acc[label] = (acc[label] || 0) + 1;
    return acc;
  }, {});
  const systemText = Object.entries(systemCounts)
    .map(([label, count]) => `${label}${count}`)
    .join('、') || '暂无系统';
  const riskText = risks
    .map((risk) => `${risk.label || riskTypeLabel(risk.hazard_type)}${evidenceLevelLabel(risk.risk_level || risk.level)} ${formatScore(risk.score)}`)
    .join('、') || '暂无风险诊断';
  return `${formatIsoForDuty(result.valid_time)}，${systemText}；${riskText}`;
}

function selectedObject() {
  if (!state.result || !state.selectedId) return null;
  if (state.selectedKind === 'risk') {
    return state.result.risk_diagnoses?.find((item) => (item.risk_id || item.hazard_type) === state.selectedId) || null;
  }
  if (state.selectedKind === 'chain') {
    return state.result.evidence_chains?.find((item) => item.id === state.selectedId) || null;
  }
  return state.result.systems?.find((item) => item.id === state.selectedId) || null;
}

function renderInspector() {
  const item = selectedObject();
  if (!item) {
    setText('inspectorTitle', '诊断详情');
    $('inspectorBody').innerHTML = '<div class="empty-state">选择天气系统或风险诊断</div>';
    return;
  }
  if (state.selectedKind === 'risk') {
    renderRiskInspector(item);
  } else if (state.selectedKind === 'chain') {
    renderChainInspector(item);
  } else {
    renderSystemInspector(item);
  }
}

function renderRiskInspector(risk) {
  setText('inspectorTitle', risk.label || riskTypeLabel(risk.hazard_type));
  const dominant = risk.dominant_evidence || [];
  const supporting = risk.supporting_systems || [];
  $('inspectorBody').innerHTML = `
    <div class="detail-stack">
      <div class="detail-grid">
        <div class="detail-item"><span>等级</span><strong>${evidenceLevelLabel(risk.risk_level || risk.level)}</strong></div>
        <div class="detail-item"><span>评分</span><strong>${formatScore(risk.score)}</strong></div>
        <div class="detail-item"><span>风险格点</span><strong>${escapeHtml(risk.source_grid || '-')}</strong></div>
        <div class="detail-item"><span>范围</span><strong>${escapeHtml(bboxLabel(risk.region))}</strong></div>
      </div>
      <div class="detail-item"><span>评分统计</span><strong>${escapeHtml(risk.score_statistic || risk.score_source || '-')}</strong></div>
      ${supporting.length ? `<div class="detail-item"><span>支撑系统</span><strong>${supporting.map((item) => escapeHtml(item.name || item.type)).join('、')}</strong></div>` : ''}
      <div class="evidence-list">
        ${dominant.map((item) => `
          <article class="evidence-item">
            <header>
              <span>${escapeHtml(item.label || item.factor || item.field)}</span>
              <span>${formatScore(item.mean_contribution)} / ${formatScore(item.weight)}</span>
            </header>
            <p>平均因子评分 ${formatScore(item.mean_score)}</p>
          </article>
        `).join('') || '<article class="evidence-item"><p>暂无主导因子</p></article>'}
      </div>
    </div>
  `;
}

function renderChainInspector(chain) {
  setText('inspectorTitle', chainTypeLabel(chain.target_type));
  const evidence = chain.evidence || [];
  const missing = chain.missing_evidence || [];
  $('inspectorBody').innerHTML = `
    <div class="detail-stack">
      <div class="detail-grid">
        <div class="detail-item"><span>等级</span><strong>${evidenceLevelLabel(chain.level)}</strong></div>
        <div class="detail-item"><span>评分</span><strong>${formatScore(chain.score)}</strong></div>
        <div class="detail-item"><span>证据数</span><strong>${evidence.length}</strong></div>
        <div class="detail-item"><span>区域</span><strong>${escapeHtml(bboxLabel(chain.region))}</strong></div>
      </div>
      ${missing.length ? `<div class="detail-item"><span>缺失证据</span><strong>${missing.map(escapeHtml).join('、')}</strong></div>` : ''}
      <div class="evidence-list">
        ${evidence.map((item) => `
          <article class="evidence-item">
            <header>
              <span>${escapeHtml(item.field)}</span>
              <span>${formatScore(item.contribution)} / ${formatScore(item.weight)}</span>
            </header>
            <p>${escapeHtml(item.signal)}，${escapeHtml(item.value)}</p>
          </article>
        `).join('')}
      </div>
    </div>
  `;
}

function renderSystemInspector(system) {
  setText('inspectorTitle', systemTypeLabel(system.type));
  const evidence = system.evidence || [];
  $('inspectorBody').innerHTML = `
    <div class="detail-stack">
      <div class="detail-grid">
        <div class="detail-item"><span>层次</span><strong>${escapeHtml(system.level || '-')}</strong></div>
        <div class="detail-item"><span>可信度</span><strong>${formatPercent((Number(system.confidence) || 0) * 100)}</strong></div>
        <div class="detail-item"><span>类型</span><strong>${escapeHtml(system.type || '-')}</strong></div>
        <div class="detail-item"><span>范围</span><strong>${escapeHtml(bboxLabel(system.geometry))}</strong></div>
      </div>
      <div class="detail-item"><span>诊断</span><strong>${escapeHtml(system.diagnosis || '-')}</strong></div>
      <div class="evidence-list">
        ${evidence.map((item) => `
          <article class="evidence-item">
            <header>
              <span>${escapeHtml(item.field)}</span>
              <span>${escapeHtml(item.signal)}</span>
            </header>
            <p>${escapeHtml(item.value || '-')}</p>
          </article>
        `).join('')}
      </div>
    </div>
  `;
}

function renderLogs() {
  const box = $('taskLog');
  if (!state.logs.length) {
    box.innerHTML = '<li><time>-</time><div><strong>暂无运行记录</strong><span>等待诊断任务</span></div></li>';
    return;
  }
  box.innerHTML = state.logs.map((log) => `
    <li>
      <time>${escapeHtml(log.time)}</time>
      <div><strong>${escapeHtml(log.status)}</strong><span>${escapeHtml(log.detail)}</span></div>
    </li>
  `).join('');
}

function renderEmpty() {
  setText('validTimeMetric', '-');
  setText('completenessMetric', '-');
  setText('systemMetric', '-');
  setText('riskMetric', '-');
  $('fieldMatrix').innerHTML = FIELD_ORDER.map((field) => `
    <span class="field-pill missing"><span>${escapeHtml(field)}</span><span>待检</span></span>
  `).join('');
  renderLogs();
}

async function bootAdmin() {
  initControls();
  initAreaRiskControls();
  initAlgorithmControls();
  setupNavigation();
  setupGovernanceDomains();
  setupGovernanceTabs();
  renderEmpty();
  const dataSourcesReady = loadDataSources();
  loadAreaRiskAreas();
  loadAlgorithmManagement();
  await dataSourcesReady;
}

bootAdmin();
