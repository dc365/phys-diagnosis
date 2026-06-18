const DEFAULT_NAFP_ROOT = '/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NEW_NC';
const DEFAULT_RUN_TIME = '2026-06-17T20:00';
const DEFAULT_FORECAST_HOUR = 24;
const FORECAST_HOURS = [0, 6, 12, 24, 36, 48, 72, 96, 120];
const FIELD_ORDER = [
  'gh500', 'uv500', 'uv850', 'q850', 'rh850', 'div850',
  'ttadv850', 'div200', 'div300', 'pv300', 'pvadv300', 'w700',
  'kindex', 'cape', 'cin', 'tcwv', 'rain6', 'shr850-200',
];

const {
  bboxLabel,
  buildNafpSituationRequest,
  chainTypeLabel,
  evidenceLevelLabel,
  formatIsoForDuty,
  formatPercent,
  formatScore,
  summarizeSituation,
  systemTypeLabel,
} = window.WeatherAdminUtils;

const state = {
  result: null,
  selectedKind: null,
  selectedId: null,
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

function levelClass(level) {
  if (level === 'high') return 'level-high';
  if (level === 'moderate') return 'level-moderate';
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
  box.className = `status-message${mode ? ` ${mode}` : ''}`;
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

function initControls() {
  $('rootInput').value = DEFAULT_NAFP_ROOT;
  $('runTimeInput').value = DEFAULT_RUN_TIME;
  FORECAST_HOURS.forEach((hour) => {
    const option = document.createElement('option');
    option.value = String(hour);
    option.textContent = hour === 0 ? '起报' : `+${hour}小时`;
    option.selected = hour === DEFAULT_FORECAST_HOUR;
    $('forecastHourSelect').appendChild(option);
  });
  $('diagnosisForm').addEventListener('submit', (event) => {
    event.preventDefault();
    runDiagnosis();
  });
}

function validatePayload(payload) {
  if (!payload.root) return '数据目录不能为空';
  if (!payload.run_time) return '起报时间不能为空';
  if (!Number.isFinite(payload.forecast_hour)) return '时效必须是数字';
  return '';
}

async function runDiagnosis() {
  const payload = buildNafpSituationRequest(
    $('rootInput').value,
    $('runTimeInput').value,
    $('forecastHourSelect').value,
  );
  const validation = validatePayload(payload);
  if (validation) {
    setStatus(validation, 'error');
    return;
  }

  const button = $('runButton');
  button.disabled = true;
  setStatus('诊断运行中');
  addLog('提交诊断', `${payload.run_time} ${payload.forecast_hour}h`);
  try {
    const result = await postJson('/api/v1/diagnosis/nafp/situation', payload);
    state.result = result;
    state.selectedKind = result.evidence_chains?.length ? 'chain' : 'system';
    state.selectedId = result.evidence_chains?.[0]?.id || result.systems?.[0]?.id || null;
    renderResult();
    setStatus(buildDutySummary(result), 'success');
    addLog('诊断完成', `${result.systems?.length || 0} 个系统，${result.evidence_chains?.length || 0} 条证据链`);
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
  setText('chainCountBadge', String(result.evidence_chains?.length || 0));
  setText('missingBadge', `${summary.missingCount} 缺测`);
  renderSystems(result.systems || []);
  renderChains(result.evidence_chains || []);
  renderFieldMatrix(result);
  renderDiagnostics(result.diagnostics || {});
  renderInspector();
}

function selectItem(kind, id) {
  state.selectedKind = kind;
  state.selectedId = id;
  renderSystems(state.result?.systems || []);
  renderChains(state.result?.evidence_chains || []);
  renderInspector();
}

function renderSystems(systems) {
  const body = $('systemsTableBody');
  if (!systems.length) {
    body.innerHTML = '<tr><td colspan="4" class="empty-cell">暂无诊断结果</td></tr>';
    return;
  }
  body.innerHTML = systems.map((system) => {
    const active = state.selectedKind === 'system' && state.selectedId === system.id ? ' active-row' : '';
    return `
      <tr class="selectable-row${active}" data-kind="system" data-id="${escapeHtml(system.id)}">
        <td><span class="type-pill">${escapeHtml(systemTypeLabel(system.type))}</span></td>
        <td>${escapeHtml(system.level || '-')}</td>
        <td class="number-col">${formatPercent((Number(system.confidence) || 0) * 100)}</td>
        <td>${escapeHtml(bboxLabel(system.geometry))}</td>
      </tr>
    `;
  }).join('');
  body.querySelectorAll('tr[data-id]').forEach((row) => {
    row.addEventListener('click', () => selectItem(row.dataset.kind, row.dataset.id));
  });
}

function renderChains(chains) {
  const box = $('chainList');
  if (!chains.length) {
    box.innerHTML = '<div class="empty-state">暂无证据链</div>';
    return;
  }
  box.innerHTML = chains.map((chain) => {
    const active = state.selectedKind === 'chain' && state.selectedId === chain.id ? ' active' : '';
    const missing = chain.missing_evidence?.length || 0;
    return `
      <button class="chain-row${active}" type="button" data-id="${escapeHtml(chain.id)}">
        <span>
          <span class="chain-row-title">
            <span class="level-pill ${levelClass(chain.level)}">${evidenceLevelLabel(chain.level)}</span>
            ${escapeHtml(chainTypeLabel(chain.target_type))}
          </span>
          <span class="chain-row-meta">${chain.evidence?.length || 0} 条证据，${missing} 项缺失</span>
        </span>
        <span class="score-value">${formatScore(chain.score)}</span>
      </button>
    `;
  }).join('');
  box.querySelectorAll('button[data-id]').forEach((button) => {
    button.addEventListener('click', () => selectItem('chain', button.dataset.id));
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

function buildDutySummary(result) {
  const systems = result.systems || [];
  const chains = result.evidence_chains || [];
  const systemCounts = systems.reduce((acc, system) => {
    const label = systemTypeLabel(system.type);
    acc[label] = (acc[label] || 0) + 1;
    return acc;
  }, {});
  const systemText = Object.entries(systemCounts)
    .map(([label, count]) => `${label}${count}`)
    .join('、') || '暂无系统';
  const chainText = chains
    .map((chain) => `${chainTypeLabel(chain.target_type)}${evidenceLevelLabel(chain.level)} ${formatScore(chain.score)}`)
    .join('、') || '暂无风险链';
  return `${formatIsoForDuty(result.valid_time)}，${systemText}；${chainText}`;
}

function selectedObject() {
  if (!state.result || !state.selectedId) return null;
  if (state.selectedKind === 'chain') {
    return state.result.evidence_chains?.find((item) => item.id === state.selectedId) || null;
  }
  return state.result.systems?.find((item) => item.id === state.selectedId) || null;
}

function renderInspector() {
  const item = selectedObject();
  if (!item) {
    setText('inspectorTitle', '证据检查器');
    $('inspectorBody').innerHTML = '<div class="empty-state">选择天气系统或风险链</div>';
    return;
  }
  if (state.selectedKind === 'chain') {
    renderChainInspector(item);
  } else {
    renderSystemInspector(item);
  }
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
            <p class="source-path">${escapeHtml(item.source_path || '-')}</p>
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
            <p class="source-path">${escapeHtml(item.source_path || '-')}</p>
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

initControls();
renderEmpty();
runDiagnosis();
