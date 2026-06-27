(function attachPrecomputeAdminExtension() {
  const API_BASE = '/api/v1/diagnosis/nafp/precompute';
  const DEFAULT_DATA_CODE = 'NAFP_ECTHIN_NC';

  function $(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  async function getJson(url) {
    const response = await fetch(url);
    const body = await response.json().catch(() => null);
    if (!response.ok || body?.code !== 0) throw new Error(body?.msg || response.statusText);
    return body.data;
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok || body?.code !== 0) throw new Error(body?.msg || response.statusText);
    return body.data;
  }

  function parseHours(value) {
    return [...new Set(String(value || '')
      .split(',')
      .map((item) => Number(item.trim()))
      .filter(Number.isFinite))]
      .sort((a, b) => a - b);
  }

  function formatTime(value) {
    const text = String(value || '');
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})/);
    return match ? `${match[2]}-${match[3]} ${match[4]}时` : text || '-';
  }

  function renderEntryRows(entries = []) {
    if (!entries.length) return '<tr><td colspan="5" class="empty-cell">暂无完成时效</td></tr>';
    return entries.map((entry) => `
      <tr>
        <td>+${esc(entry.forecast_hour)}h</td>
        <td>${esc(entry.cache_status || '-')}</td>
        <td class="number-col">${esc(entry.compute_ms ?? '-')}</td>
        <td class="number-col">${esc(entry.system_count ?? '-')}</td>
        <td class="number-col">${esc(entry.risk_count ?? '-')}</td>
      </tr>
    `).join('');
  }

  function renderJob(job) {
    if (!job) return '<div class="empty-state">暂无预计算任务。服务启动后会自动为最新起报时次创建任务。</div>';
    const percent = Math.round(Number(job.progress || 0) * 100);
    const failedText = (job.failed || []).length
      ? `<p class="status-message error">失败：${(job.failed || []).map((item) => `+${esc(item.forecast_hour)}h ${esc(item.error)}`).join('；')}</p>`
      : '';
    return `
      <section class="precompute-job-card">
        <div class="section-head compact-head">
          <div>
            <span class="panel-kicker">${esc(job.data_code || DEFAULT_DATA_CODE)} · ${esc(formatTime(job.run_time))}</span>
            <h4>任务 ${esc(job.job_id || '-')}</h4>
          </div>
          <span class="count-badge">${esc(job.status || 'unknown')}</span>
        </div>
        <div class="precompute-progress" aria-label="预计算进度"><span style="width:${percent}%"></span></div>
        <div class="detail-grid compact-detail-grid">
          <div class="detail-item"><span>进度</span><strong>${percent}%</strong></div>
          <div class="detail-item"><span>完成</span><strong>${esc(job.completed_count || 0)}/${esc(job.total_count || 0)}</strong></div>
          <div class="detail-item"><span>失败</span><strong>${esc(job.failed_count || 0)}</strong></div>
          <div class="detail-item"><span>复用</span><strong>${esc(job.hit_count || 0)}</strong></div>
        </div>
        <div class="table-wrap diagnostics-wrap">
          <table>
            <thead><tr><th>时效</th><th>状态</th><th class="number-col">耗时ms</th><th class="number-col">系统</th><th class="number-col">风险</th></tr></thead>
            <tbody>${renderEntryRows(job.entries || [])}</tbody>
          </table>
        </div>
        ${failedText}
      </section>
    `;
  }

  function ensurePanel() {
    if ($('nafpPrecomputePanel')) return $('nafpPrecomputePanel');
    const serviceGrid = document.querySelector('#service-status .service-grid') || document.querySelector('#service-status');
    if (!serviceGrid) return null;
    const panel = document.createElement('section');
    panel.className = 'section-panel precompute-panel';
    panel.id = 'nafpPrecomputePanel';
    panel.innerHTML = `
      <div class="section-head">
        <div>
          <span class="panel-kicker">预计算</span>
          <h3>NAFP 数值预报诊断预计算</h3>
        </div>
        <span id="precomputeStatusBadge" class="count-badge">idle</span>
      </div>
      <p class="muted-copy">后端自动预计算最新起报时次。地图页面加载天气系统时只读取预计算结果；结果未准备好时会自动排队，不在地图请求线程里重复计算。</p>
      <form id="precomputeForm" class="precompute-inline-form">
        <label><span>资料编码</span><select id="precomputeDataCode"></select></label>
        <label><span>起报时次</span><select id="precomputeRunTime"></select></label>
        <label><span>预报时效</span><input id="precomputeHours" value="0,24,48,72" /></label>
        <label><span>强制重算</span><select id="precomputeForce"><option value="false" selected>否</option><option value="true">是</option></select></label>
        <div class="precompute-actions">
          <button class="primary-action" type="submit">提交预计算</button>
          <button id="precomputeRefresh" class="ghost-button" type="button">刷新状态</button>
        </div>
      </form>
      <div id="precomputeLatestJob" class="precompute-latest"><div class="empty-state">加载任务状态</div></div>
      <details class="precompute-history">
        <summary>最近任务</summary>
        <div id="precomputeJobList" class="precompute-job-list"></div>
      </details>
    `;
    serviceGrid.appendChild(panel);
    return panel;
  }

  async function loadRunTimes() {
    const dataCode = $('precomputeDataCode')?.value || DEFAULT_DATA_CODE;
    const select = $('precomputeRunTime');
    if (!select) return;
    try {
      const payload = await getJson(`/api/v1/admin/data-sources/${encodeURIComponent(dataCode)}/nafp-runs?_=${Date.now()}`);
      const runs = payload.run_times || [];
      select.innerHTML = runs.map((run) => `<option value="${esc(run.run_time)}" data-hours="${esc((run.forecast_hours || []).join(','))}">${esc(formatTime(run.run_time))}</option>`).join('');
      if (payload.default_run_time) select.value = payload.default_run_time;
      const hours = select.selectedOptions[0]?.dataset.hours;
      if (hours && $('precomputeHours')) $('precomputeHours').value = hours;
    } catch (error) {
      select.innerHTML = '<option value="">未发现起报时次</option>';
    }
  }

  async function loadDataSources() {
    const select = $('precomputeDataCode');
    if (!select) return;
    try {
      const payload = await getJson('/api/v1/admin/data-sources');
      const items = (payload.items || []).filter((item) => item.enabled !== false);
      select.innerHTML = items.map((item) => `<option value="${esc(item.code)}">${esc(item.label || item.code)}</option>`).join('');
      select.value = payload.default_code || items[0]?.code || DEFAULT_DATA_CODE;
    } catch (error) {
      select.innerHTML = `<option value="${DEFAULT_DATA_CODE}">${DEFAULT_DATA_CODE}</option>`;
    }
    await loadRunTimes();
  }

  async function refreshStatus() {
    const payload = await getJson(`${API_BASE}/status?_=${Date.now()}`);
    const statusBadge = $('precomputeStatusBadge');
    if (statusBadge) statusBadge.textContent = `${payload.status || 'idle'} · ${payload.result_file_count || 0}文件`;
    const latest = $('precomputeLatestJob');
    if (latest) latest.innerHTML = renderJob(payload.latest_job);
    const list = $('precomputeJobList');
    if (list) {
      list.innerHTML = (payload.jobs || []).length
        ? (payload.jobs || []).map((job) => renderJob(job)).join('')
        : '<div class="empty-state">暂无历史任务</div>';
    }
  }

  async function submitPrecompute(event) {
    event.preventDefault();
    const forecastHours = parseHours($('precomputeHours')?.value);
    if (!forecastHours.length) {
      alert('请填写至少一个预报时效');
      return;
    }
    await postJson(`${API_BASE}/run`, {
      data_code: $('precomputeDataCode')?.value || DEFAULT_DATA_CODE,
      run_time: $('precomputeRunTime')?.value,
      forecast_hours: forecastHours,
      force: $('precomputeForce')?.value === 'true',
    });
    await refreshStatus();
  }

  function bindEvents() {
    $('precomputeDataCode')?.addEventListener('change', () => loadRunTimes().catch((error) => console.warn(error)));
    $('precomputeRunTime')?.addEventListener('change', () => {
      const hours = $('precomputeRunTime')?.selectedOptions[0]?.dataset.hours;
      if (hours && $('precomputeHours')) $('precomputeHours').value = hours;
    });
    $('precomputeRefresh')?.addEventListener('click', () => refreshStatus().catch((error) => alert(error.message)));
    $('precomputeForm')?.addEventListener('submit', (event) => submitPrecompute(event).catch((error) => alert(error.message)));
  }

  function injectStyles() {
    if ($('precomputeAdminExtensionStyles')) return;
    const style = document.createElement('style');
    style.id = 'precomputeAdminExtensionStyles';
    style.textContent = `
      .precompute-panel { grid-column: 1 / -1; }
      .precompute-inline-form { display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 12px; align-items: end; margin: 12px 0 16px; }
      .precompute-inline-form label { display: grid; gap: 6px; font-size: 13px; color: #435d68; }
      .precompute-inline-form select, .precompute-inline-form input { border: 1px solid #c7d7df; border-radius: 10px; padding: 10px 12px; background: white; font: inherit; min-width: 0; }
      .precompute-actions { display: flex; gap: 8px; flex-wrap: wrap; }
      .precompute-progress { height: 12px; border-radius: 999px; overflow: hidden; background: #d7e4ea; }
      .precompute-progress span { display: block; height: 100%; background: linear-gradient(90deg, #228be6, #12b886); transition: width 0.25s ease; }
      .precompute-job-card { display: grid; gap: 10px; border: 1px solid #dde9ee; border-radius: 14px; padding: 14px; background: #fff; margin-bottom: 10px; }
      .precompute-job-list { display: grid; gap: 10px; margin-top: 10px; }
      .muted-copy { color: #6b818a; margin: 0; }
      @media (max-width: 920px) { .precompute-inline-form { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  async function init() {
    if (!ensurePanel()) return;
    injectStyles();
    bindEvents();
    await loadDataSources();
    await refreshStatus();
    setInterval(() => refreshStatus().catch(() => {}), 3000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init().catch((error) => console.warn(error)));
  else init().catch((error) => console.warn(error));
})();
