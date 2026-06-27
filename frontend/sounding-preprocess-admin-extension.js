(function attachSoundingPreprocessAdminExtension() {
  const API_BASE = '/api/v1/sounding/preprocess';

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

  function percent(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    return `${(n * 100).toFixed(1)}%`;
  }

  function flagRows(report) {
    const counts = report?.flag_counts || {};
    const rows = Object.entries(counts).sort((a, b) => Number(b[1]) - Number(a[1]));
    if (!rows.length) return '<span class="muted-copy">无剔除标记</span>';
    return rows.slice(0, 8).map(([flag, count]) => `<span class="qc-flag-chip">${esc(flag)} ${esc(count)}</span>`).join('');
  }

  function renderReport(report) {
    if (!report) return '<div class="empty-state">暂无预处理报告</div>';
    const profile = report.profile || {};
    return `
      <article class="sounding-qc-report-card">
        <div class="section-head compact-head">
          <div>
            <span class="panel-kicker">${esc(report.source_path || '-')}</span>
            <h4>${esc(report.quality_level || 'review')} · ${esc(report.accepted_row_count || 0)}/${esc(report.row_count || 0)} 行通过</h4>
          </div>
          <span class="count-badge">剔除 ${esc(report.rejected_row_count || 0)}</span>
        </div>
        <div class="detail-grid compact-detail-grid">
          <div class="detail-item"><span>站点数</span><strong>${esc(profile.station_count || 0)}</strong></div>
          <div class="detail-item"><span>弱廓线站</span><strong>${esc(profile.weak_profile_station_count || 0)}</strong></div>
          <div class="detail-item"><span>中位层数</span><strong>${esc(profile.profile_level_count_median ?? '-')}</strong></div>
          <div class="detail-item"><span>剔除率</span><strong>${esc(percent(report.reject_rate))}</strong></div>
        </div>
        <div class="qc-flag-list">${flagRows(report)}</div>
        <details>
          <summary>标准层覆盖率</summary>
          <div class="qc-level-grid">
            ${Object.entries(profile.standard_level_coverage || {}).map(([level, coverage]) => `<span>${esc(level)} <strong>${esc(percent(coverage))}</strong></span>`).join('')}
          </div>
        </details>
      </article>
    `;
  }

  function ensurePanel() {
    if ($('soundingPreprocessPanel')) return $('soundingPreprocessPanel');
    const host = document.querySelector('#data-fields .data-grid') || document.querySelector('#service-status .service-grid') || document.querySelector('#data-fields');
    if (!host) return null;
    const panel = document.createElement('section');
    panel.className = 'section-panel sounding-preprocess-panel';
    panel.id = 'soundingPreprocessPanel';
    panel.innerHTML = `
      <div class="section-head">
        <div>
          <span class="panel-kicker">探空实况</span>
          <h3>探空站资料预处理</h3>
        </div>
        <span id="soundingPreprocessBadge" class="count-badge">0 报告</span>
      </div>
      <p class="muted-copy">预处理包括字段标准化、单位数值化、经纬度/层次/温湿风范围检查、露点约束、重复站层去重、500hPa 高度 buddy check、标准层覆盖率和弱廓线统计。优化后的 H500 分析会优先使用清洗后的 CSV。</p>
      <form id="soundingPreprocessForm" class="sounding-qc-form">
        <label><span>CSV 文件</span><select id="soundingPreprocessFile"></select></label>
        <label><span>强制重跑</span><select id="soundingPreprocessForce"><option value="false" selected>否</option><option value="true">是</option></select></label>
        <div class="sounding-qc-actions">
          <button class="primary-action" type="submit">运行预处理</button>
          <button id="soundingPreprocessAll" class="ghost-button" type="button">全部预处理</button>
          <button id="soundingPreprocessRefresh" class="ghost-button" type="button">刷新</button>
        </div>
      </form>
      <div id="soundingPreprocessSummary" class="detail-grid compact-detail-grid"></div>
      <div id="soundingPreprocessReports" class="sounding-qc-report-list"><div class="empty-state">加载探空预处理状态</div></div>
    `;
    host.appendChild(panel);
    return panel;
  }

  function renderFileOptions(status) {
    const select = $('soundingPreprocessFile');
    if (!select) return;
    const files = status?.available_files || [];
    select.innerHTML = files.map((item) => `
      <option value="${esc(item.path)}">${esc(item.file_name || item.path)}${item.has_report ? ' · 已处理' : ''}</option>
    `).join('');
    if (!select.innerHTML) select.innerHTML = '<option value="">未发现探空CSV</option>';
  }

  function renderSummary(status) {
    const badge = $('soundingPreprocessBadge');
    if (badge) badge.textContent = `${status?.report_count || 0} 报告`;
    const summary = $('soundingPreprocessSummary');
    if (!summary) return;
    summary.innerHTML = `
      <div class="detail-item"><span>CSV 文件</span><strong>${esc(status?.available_file_count || 0)}</strong></div>
      <div class="detail-item"><span>报告数</span><strong>${esc(status?.report_count || 0)}</strong></div>
      <div class="detail-item"><span>最近更新时间</span><strong>${esc(status?.updated_at || '-')}</strong></div>
    `;
  }

  function renderReports(status) {
    const box = $('soundingPreprocessReports');
    if (!box) return;
    const reports = status?.reports || [];
    box.innerHTML = reports.length ? reports.map(renderReport).join('') : '<div class="empty-state">暂无预处理报告</div>';
  }

  async function refreshStatus() {
    const status = await getJson(`${API_BASE}/status?_=${Date.now()}`);
    renderFileOptions(status);
    renderSummary(status);
    renderReports(status);
  }

  async function runSelected(event) {
    event.preventDefault();
    const csvPath = $('soundingPreprocessFile')?.value;
    if (!csvPath) {
      alert('未发现可处理的 CSV 文件');
      return;
    }
    await postJson(`${API_BASE}/run`, {
      csv_path: csvPath,
      force: $('soundingPreprocessForce')?.value === 'true',
    });
    await refreshStatus();
  }

  async function runAll() {
    await postJson(`${API_BASE}/run`, { force: $('soundingPreprocessForce')?.value === 'true' });
    await refreshStatus();
  }

  function injectStyles() {
    if ($('soundingPreprocessAdminStyles')) return;
    const style = document.createElement('style');
    style.id = 'soundingPreprocessAdminStyles';
    style.textContent = `
      .sounding-preprocess-panel { grid-column: 1 / -1; }
      .sounding-qc-form { display: grid; grid-template-columns: minmax(260px, 1fr) 140px auto; gap: 12px; align-items: end; margin: 12px 0 16px; }
      .sounding-qc-form label { display: grid; gap: 6px; font-size: 13px; color: #435d68; }
      .sounding-qc-form select { border: 1px solid #c7d7df; border-radius: 10px; padding: 10px 12px; background: white; font: inherit; min-width: 0; }
      .sounding-qc-actions { display: flex; gap: 8px; flex-wrap: wrap; }
      .sounding-qc-report-list { display: grid; gap: 12px; margin-top: 12px; }
      .sounding-qc-report-card { border: 1px solid #dde9ee; border-radius: 14px; background: #fff; padding: 14px; display: grid; gap: 10px; }
      .qc-flag-list { display: flex; flex-wrap: wrap; gap: 6px; }
      .qc-flag-chip { border-radius: 999px; background: #edf4fb; color: #375566; padding: 4px 8px; font-size: 12px; }
      .qc-level-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 6px; margin-top: 8px; }
      .qc-level-grid span { background: #f7fbfd; border-radius: 8px; padding: 6px 8px; }
      .muted-copy { color: #6b818a; margin: 0; }
      @media (max-width: 920px) { .sounding-qc-form { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function bindEvents() {
    $('soundingPreprocessForm')?.addEventListener('submit', (event) => runSelected(event).catch((error) => alert(error.message)));
    $('soundingPreprocessAll')?.addEventListener('click', () => runAll().catch((error) => alert(error.message)));
    $('soundingPreprocessRefresh')?.addEventListener('click', () => refreshStatus().catch((error) => alert(error.message)));
  }

  async function init() {
    if (!ensurePanel()) return;
    injectStyles();
    bindEvents();
    await refreshStatus();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init().catch((error) => console.warn(error)));
  else init().catch((error) => console.warn(error));
})();
