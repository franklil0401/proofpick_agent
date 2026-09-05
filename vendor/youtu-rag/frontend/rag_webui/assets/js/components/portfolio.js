(function () {
  'use strict';

  const state = { bundle: null, domain: 'headphone', mode: 'trusted', runMode: 'replay', memoryScope: 'category' };
  const domainLabels = { monitor: '显示器', laptop: '笔记本', headphone: '耳机' };
  const examples = {
    monitor: ['27 英寸 4K，USB-C 供电至少 90W', 'PD2705U 到底是 60W 还是 65W？'],
    laptop: ['至少 64GB 内存，按便携场景排序', '比较 H7606WI 与 H7606WW 的配置'],
    headphone: ['主动降噪，重量不超过 250g', '研究库外 AirPods Max 2 官方规格']
  };
  const memoryKeys = {
    monitor: ['budget_max_cny', 'display_size_inch', 'resolution', 'min_refresh_rate_hz', 'exclude_oled', 'excluded_brands', 'primary_use', 'ranking_scenario'],
    laptop: ['budget_max_cny', 'preferred_cpu_family', 'min_memory_gb', 'min_storage_gb', 'max_weight_kg', 'need_thunderbolt', 'excluded_brands', 'primary_use', 'ranking_scenario'],
    headphone: ['preferred_form_factor', 'preferred_connection', 'preferred_codec', 'preferred_platform', 'preferred_scenario', 'max_weight_g', 'anc_preference', 'excluded_brands', 'ranking_scenario']
  };

  function confirmExperimentalResearch() {
    return window.confirm(
      'Online Research 是 Experimental/Beta：不保证找到目标地区官方页面或完成网页提取；失败将返回 unknown，临时 Open Evidence 不会进入 Trusted Checker。是否继续？'
    );
  }

  const byId = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  const identity = () => {
    let value = localStorage.getItem('proofpick-v2-browser-identity');
    if (!value) {
      value = (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      localStorage.setItem('proofpick-v2-browser-identity', value);
    }
    return value;
  };

  async function loadBundle() {
    const response = await fetch('assets/data/proofpick-demos.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('离线回放数据不可用');
    state.bundle = await response.json();
    const requested = new URLSearchParams(window.location.search).get('demo');
    const requestedDemo = state.bundle.demos.find((item) => item.demo_id === requested);
    const acceptedRequestedDemo = requestedDemo && (
      requestedDemo.mode !== 'open' || confirmExperimentalResearch()
    );
    if (acceptedRequestedDemo) {
      state.domain = requestedDemo.domain_id;
      state.mode = requestedDemo.mode;
    }
    populateDemos(acceptedRequestedDemo ? requestedDemo.demo_id : undefined);
    const initial = acceptedRequestedDemo ? requestedDemo.demo_id : byId('demo-select').value;
    selectDemo(initial, true);
  }

  function demosForSelection() {
    const exact = state.bundle.demos.filter((demo) => demo.domain_id === state.domain && demo.mode === state.mode);
    return exact.length ? exact : state.bundle.demos.filter((demo) => demo.domain_id === state.domain);
  }

  function populateDemos(selectedId) {
    if (!state.bundle) return;
    const select = byId('demo-select');
    const candidates = demosForSelection();
    select.innerHTML = candidates.map((demo) => `<option value="${esc(demo.demo_id)}">${esc(demo.title)}</option>`).join('');
    select.value = selectedId && candidates.some((demo) => demo.demo_id === selectedId)
      ? selectedId : (candidates[0] || state.bundle.demos[0]).demo_id;
  }

  function selectedDemo() {
    return state.bundle.demos.find((demo) => demo.demo_id === byId('demo-select').value) || state.bundle.demos[0];
  }

  function updateSelectionUI() {
    document.querySelectorAll('[data-domain]').forEach((button) => button.classList.toggle('active', button.dataset.domain === state.domain));
    document.querySelectorAll('[data-research-mode]').forEach((button) => button.classList.toggle('active', button.dataset.researchMode === state.mode));
    document.querySelectorAll('[data-run-mode]').forEach((button) => button.classList.toggle('active', button.dataset.runMode === state.runMode));
    const demo = selectedDemo();
    byId('version-card').innerHTML = `DOMAIN PACK 1.0.0<br>DATA ${esc(demo.data_version)}<br>INDEX ${esc(demo.index_version)}<br>UPDATED ${esc(demo.evidence[0]?.observed_at || 'versioned manifest')}`;
    byId('run-notice').innerHTML = state.mode === 'open'
      ? '<b>Online Research · Experimental/Beta</b> · 不保证官方地区页或网页提取成功；失败返回 unknown。Open Evidence 不进入 Trusted Checker，安全 unknown 不算研究完成。'
      : (state.runMode === 'replay'
        ? '<b>Trusted Mode · Stable</b> · 当前为固定脱敏回放，不是实时模型调用，不包含 Prompt、Key、私人路径或隐藏推理。'
        : '<b>Trusted Mode · Stable</b> · 需要本机已配置运行时；失败会明确显示 online_unavailable，不会伪装成回放。');
    byId('run-button').innerHTML = state.runMode === 'replay' ? '播放脱敏轨迹 <span>→</span>' : '启动在线 Agent <span>→</span>';
    byId('hero-route').textContent = `${state.domain.toUpperCase()} / ${state.mode.toUpperCase()}`;
    byId('hero-pool').textContent = `${demo.complete_candidate_pool_size} CONFIGS`;
    renderExamples();
    renderMemoryKeys();
  }

  function selectDemo(id, renderNow) {
    const demo = state.bundle.demos.find((item) => item.demo_id === id);
    if (!demo) return;
    state.domain = demo.domain_id;
    state.mode = demo.mode;
    byId('demo-select').value = demo.demo_id;
    byId('proofpick-query').value = demo.query;
    updateCounter();
    updateSelectionUI();
    if (renderNow) renderDemo(demo);
  }

  function renderExamples() {
    byId('example-row').innerHTML = examples[state.domain].map((query) => `<button type="button">${esc(query)}</button>`).join('');
    byId('example-row').querySelectorAll('button').forEach((button) => button.addEventListener('click', () => {
      byId('proofpick-query').value = button.textContent;
      updateCounter();
    }));
  }

  function renderCandidate(candidate) {
    const dimensions = candidate.dimensions.map((item) => `<div class="dimension">${esc(item.id)} · 权重 ${esc(item.weight ?? '—')} · 贡献 ${esc(item.contribution ?? item.status ?? '—')}<br><code>${esc(item.evidence ?? '')}</code></div>`).join('');
    return `<article class="candidate ${esc(candidate.checker_status)}"><span class="candidate-state">${esc(candidate.checker_status.toUpperCase())}</span><h4>${candidate.rank ? `#${candidate.rank} ` : ''}${esc(candidate.label)}</h4><small>${esc(candidate.region)} · ${esc(candidate.configuration)}</small><p>${esc(candidate.reason)}</p>${candidate.score !== null ? `<div class="score">SCORE ${candidate.score.toFixed(4)}</div>` : ''}${dimensions}${candidate.unknown_fields.length ? `<div class="chips"><span class="chip warn">unknown: ${esc(candidate.unknown_fields.join(', '))}</span></div>` : ''}</article>`;
  }

  function renderTrace(trace) {
    return trace.map((item) => `<div class="trace-item ${esc(item.status)}"><span>${String(item.step).padStart(2, '0')}</span><b>${esc(item.category)}</b><p><strong>${esc(item.status)}</strong> · ${esc(item.output_summary)}<br><code>${esc(item.version)}</code></p><time>${item.duration_ms.toFixed(1)}ms</time></div>`).join('');
  }

  function renderEvidence(evidence) {
    return evidence.map((item) => `<div class="evidence-row"><a href="${esc(item.source_url)}" target="_blank" rel="noreferrer">${esc(item.evidence_id)}</a><span>${esc(item.field)} = ${esc(typeof item.value === 'object' ? JSON.stringify(item.value) : item.value)}</span><code>${esc(item.region)} / ${esc(item.configuration)}<br>${esc(item.observed_at)}</code></div>`).join('');
  }

  function renderDemo(demo) {
    byId('hero-run-state').textContent = state.runMode === 'replay' ? 'REPLAY COMPLETE' : 'ONLINE COMPLETE';
    const hard = demo.hard_constraints.map((item) => `<span class="chip hard">${esc(item)}</span>`).join('') || '<span class="chip">无硬约束</span>';
    const soft = demo.soft_preferences.map((item) => `<span class="chip">${esc(item)}</span>`).join('');
    const notices = [...demo.degraded_states, ...demo.conflicts];
    const memory = demo.memory_story.length ? `<section class="result-section"><h3>Memory 与连续追问 <span>${demo.memory_story.length} 步</span></h3><ol>${demo.memory_story.map((item) => `<li>${esc(item)}</li>`).join('')}</ol></section>` : '';
    const dynamic = demo.dynamic_observation ? `<section class="result-section"><h3>动态观察 <span>${esc(demo.dynamic_observation.status)}</span></h3><div class="degraded-box">${esc(demo.dynamic_observation.currency)} · observed_at ${esc(demo.dynamic_observation.observed_at)} · TTL ${demo.dynamic_observation.ttl_seconds / 3600}h · expired=${esc(demo.dynamic_observation.expired)}<br>${esc(demo.dynamic_observation.reason)}；不进入 Checker / Memory / 稳定规格。</div></section>` : '';
    const modeLabel = demo.mode === 'open' ? 'ONLINE RESEARCH · EXPERIMENTAL' : 'TRUSTED MODE · STABLE';
    byId('result-panel').innerHTML = `<div class="result-head"><div><span class="section-kicker">02 / DECISION REPORT</span><h2>${esc(demo.title)}</h2><p>${esc(demo.query)}</p></div><span class="status-badge ${demo.mode === 'open' ? 'open' : ''}">${modeLabel}</span></div>
      <div class="summary-grid"><div><span>QUERY INTENT</span><strong>${esc(demo.query_intent)}</strong></div><div><span>COMPLETE POOL</span><strong>${demo.complete_candidate_pool_size}</strong></div><div><span>CHECKER ELIGIBLE</span><strong>${demo.candidates.filter((item) => item.checker_status === 'eligible').length}</strong></div><div><span>EVIDENCE</span><strong>${demo.evidence.length} shown</strong></div></div>
      <section class="result-section"><h3>约束与偏好 <span>${demo.constraint_sources.length} 个来源</span></h3><div class="chips">${hard}${soft}</div><div class="chips" style="margin-top:7px">${demo.constraint_sources.map((item) => `<span class="chip">${esc(item)}</span>`).join('')}</div></section>
      ${demo.clarification.length ? `<section class="result-section"><h3>待澄清</h3><div class="chips">${demo.clarification.map((item) => `<span class="chip warn">${esc(item)}</span>`).join('')}</div></section>` : ''}
      <section class="result-section"><h3>候选与安全门 <span>${demo.candidates.length} 个重点候选</span></h3><div class="candidate-grid">${demo.candidates.map(renderCandidate).join('')}</div></section>
      ${dynamic}${memory}
      <section class="result-section"><h3>公开工具轨迹 <span>不含隐藏思维链</span></h3><div class="trace">${renderTrace(demo.trace)}</div></section>
      <details open><summary>Evidence、来源、地区与配置</summary><div class="evidence-list">${renderEvidence(demo.evidence)}</div></details>
      ${notices.length ? `<div class="degraded-box"><b>降级 / 冲突</b><br>${notices.map(esc).join('<br>')}</div>` : ''}
      <div class="degraded-box" style="background:#eef3ee;color:#435047"><b>停止原因</b> · ${esc(demo.stop_reason)}<br><b>审计证据</b> · ${esc(demo.run_evidence)}<br><b>声明</b> · ${esc(state.bundle.disclosure)}</div>`;
  }

  async function runSelected() {
    const button = byId('run-button');
    const demo = selectedDemo();
    button.disabled = true;
    byId('result-panel').innerHTML = '<div class="loader"><i></i><h2>正在执行有界步骤</h2><p>工具调用、Checker 与降级状态会在完成后展示。</p></div>';
    byId('hero-run-state').textContent = state.runMode === 'replay' ? 'PLAYING REPLAY' : 'ONLINE RUNNING';
    try {
      if (state.runMode === 'replay') {
        await new Promise((resolve) => setTimeout(resolve, 420));
        renderDemo(demo);
        return;
      }
      const response = await fetch('/api/smartbuy/portfolio/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ProofPick-Identity': identity() },
        body: JSON.stringify({ domain_id: state.domain, mode: state.mode, query: byId('proofpick-query').value, session_id: `ui-${Date.now()}`, user_id: identity(), use_long_term_memory: byId('memory-enabled').checked })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.message || payload.detail || 'online_unavailable');
      renderOnlineReport(payload);
    } catch (error) {
      byId('hero-run-state').textContent = 'ONLINE UNAVAILABLE';
      byId('result-panel').innerHTML = `<div class="empty-result"><span class="empty-orbit">!</span><h2>online_unavailable</h2><p>${esc(error.message)}。本地可信路径未被伪装为成功；你可以切回“离线回放”查看固定脱敏结果。</p><button class="primary" id="fallback-replay">切换到离线回放</button></div>`;
      byId('fallback-replay').addEventListener('click', () => { state.runMode = 'replay'; updateSelectionUI(); renderDemo(demo); });
    } finally { button.disabled = false; }
  }

  function renderOnlineReport(payload) {
    const report = payload.report;
    const rankingRows = new Map((report.ranking?.candidate_contributions || []).map((item) => [item.product_id, item]));
    const candidates = (report.candidates || []).map((item) => {
      const ranked = rankingRows.get(item.model_id);
      const status = item.eligible ? 'eligible'
        : item.conflict_fields?.length ? 'conflict'
          : item.unknown_fields?.length ? 'unknown' : 'eliminated';
      return {
        product_id: item.model_id,
        label: item.model_name || item.model_id,
        region: item.region || 'unknown',
        configuration: item.configuration_id || 'unknown',
        checker_status: status,
        reason: item.recommendation_reason || item.elimination_reason || item.overall_status,
        rank: ranked?.rank || item.rank || null,
        score: ranked?.total_score ?? item.ranking_score ?? null,
        dimensions: (ranked?.dimension_scores || []).map((dimension) => ({
          id: dimension.dimension_id,
          weight: dimension.weight,
          contribution: dimension.contribution,
          status: dimension.status,
          evidence: (dimension.evidence_ids || []).join(', ')
        })),
        unknown_fields: item.unknown_fields || []
      };
    });
    const evidence = (report.evidence || []).filter((item) => item.source_url).map((item) => ({
      evidence_id: item.evidence_id || item.source_id,
      field: item.field || 'source',
      value: item.value,
      source_url: item.source_url,
      region: item.region || 'unknown',
      configuration: item.configuration_id || 'unknown',
      observed_at: item.effective_time || 'versioned source',
      status: 'matched'
    }));
    const traceCategories = {
      category_router: 'Category Router', constraint_resolution: 'Constraint Resolution',
      product_scope: 'Product Scope', product_query: 'Product Query/Text2SQL',
      text2sql: 'Product Query/Text2SQL', kb_search: 'KB Search', reranker: 'Reranker',
      evidence_check: 'Evidence Check', constraint_checker: 'Constraint Checker',
      decision_ranker: 'Decision Ranker', memory: 'Memory', report: 'Report'
    };
    const trace = (report.trace || []).map((item, index) => ({
      step: index + 1,
      category: traceCategories[item.tool] || traceCategories[item.task_summary] || 'Report',
      status: item.status === 'failed' ? 'blocked' : item.status,
      duration_ms: item.duration_ms || 0,
      degraded: item.status === 'degraded',
      input_summary: item.task_summary || '公开参数摘要',
      output_summary: item.result_summary || item.next_action || '完成',
      version: report.usage?.data_version || payload.data_version || 'runtime'
    }));
    if (!trace.length) {
      trace.push({ step: 1, category: 'Report', status: 'success', duration_ms: report.latency_ms || 0, degraded: false, input_summary: '在线请求', output_summary: '结构化报告已生成', version: payload.data_version || 'runtime' });
    }
    const hardConstraints = (report.constraint_set?.constraints || report.hard_constraints || []).filter((item) => (item.hard_or_soft || 'hard') === 'hard').map((item) => `${item.field || item.field_name} ${item.operator} ${item.normalized_value ?? item.value}`);
    const adapted = {
      demo_id: 'online-result', title: `在线结果 · ${domainLabels[state.domain]}`,
      domain_id: state.domain, mode: state.mode, query: report.request_summary,
      query_intent: report.query_intent || report.task_type,
      hard_constraints: hardConstraints,
      soft_preferences: report.soft_preferences || [],
      clarification: [...(report.pending_questions || []), ...(report.clarification_state === 'required' ? ['需要用户确认后恢复执行'] : [])],
      constraint_sources: ['当前输入', ...(report.usage?.memory_enabled ? ['已确认 Memory'] : [])],
      complete_candidate_pool_size: report.usage?.complete_candidate_pool_size || report.product_scope?.product_ids?.length || 0,
      candidates, evidence, trace,
      stop_reason: report.stop_reason,
      degraded_states: report.degraded_states || [],
      conflicts: (report.unresolved_facts || []).filter((item) => item.status === 'conflict').map((item) => `${item.field}: ${item.reason}`),
      data_version: report.usage?.data_version || payload.data_version,
      index_version: report.usage?.index_version || payload.index_version,
      run_evidence: '当前本机 API 的脱敏结构化响应', real_run_command: 'smartbuy/scripts/start.ps1',
      dynamic_observation: null, memory_story: []
    };
    renderDemo(adapted);
  }

  function updateCounter() { byId('query-count').textContent = `${byId('proofpick-query').value.length} / 2000`; }

  function renderMemoryKeys() {
    const keys = state.memoryScope === 'global' ? ['excluded_brands'] : memoryKeys[state.domain];
    byId('memory-key').innerHTML = keys.map((key) => `<option value="${esc(key)}">${esc(key)}</option>`).join('');
  }

  async function memoryRequest(method, path, body) {
    const userId = identity();
    const response = await fetch(`/api/smartbuy/memory/${encodeURIComponent(userId)}${path || ''}`, { method, headers: { 'Content-Type': 'application/json', 'X-ProofPick-Identity': userId }, body: body ? JSON.stringify(body) : undefined });
    if (!response.ok) throw new Error('Memory API unavailable');
    return response.json();
  }

  async function refreshMemory() {
    byId('memory-identity').textContent = `${identity().slice(0, 8)}…（仅本浏览器）`;
    if (!byId('memory-enabled').checked) { byId('memory-records').innerHTML = '<p class="muted">Memory 已关闭；当前输入仍可正常执行。</p>'; return; }
    try {
      const data = await memoryRequest('GET', `?domain_id=${state.domain}`);
      const records = data.records?.[state.memoryScope] || {};
      byId('memory-records').innerHTML = Object.keys(records).length ? Object.entries(records).map(([key, record]) => `<div class="memory-record"><span><b>${esc(key)}</b><br><code>${esc(JSON.stringify(record.value))}</code> · ${esc(record.status)}</span><button type="button" data-delete-memory="${esc(key)}">删除</button></div>`).join('') : '<p class="muted">当前范围没有已确认偏好。</p>';
      byId('memory-records').querySelectorAll('[data-delete-memory]').forEach((button) => button.addEventListener('click', async () => { await memoryRequest('DELETE', '', { domain_id: state.domain, scope: state.memoryScope, fields: [button.dataset.deleteMemory] }); await refreshMemory(); }));
    } catch (error) { byId('memory-records').innerHTML = `<p class="muted">${esc(error.message)}；未使用不可靠身份回退。</p>`; }
  }

  function parseMemoryValue(raw) { try { return JSON.parse(raw); } catch (_) { return raw; } }

  function bindEvents() {
    document.querySelectorAll('[data-domain]').forEach((button) => button.addEventListener('click', () => { state.domain = button.dataset.domain; populateDemos(); selectDemo(byId('demo-select').value, false); }));
    document.querySelectorAll('[data-research-mode]').forEach((button) => button.addEventListener('click', () => {
      const nextMode = button.dataset.researchMode;
      if (nextMode === 'open' && state.mode !== 'open' && !confirmExperimentalResearch()) return;
      state.mode = nextMode;
      populateDemos();
      selectDemo(byId('demo-select').value, false);
    }));
    document.querySelectorAll('[data-run-mode]').forEach((button) => button.addEventListener('click', () => { state.runMode = button.dataset.runMode; updateSelectionUI(); }));
    byId('demo-select').addEventListener('change', (event) => selectDemo(event.target.value, false));
    byId('proofpick-query').addEventListener('input', updateCounter);
    byId('run-button').addEventListener('click', runSelected);
    const drawer = byId('memory-drawer'); const backdrop = byId('drawer-backdrop');
    const closeDrawer = () => { drawer.classList.remove('open'); backdrop.classList.remove('open'); drawer.setAttribute('aria-hidden', 'true'); };
    byId('memory-open').addEventListener('click', () => { drawer.classList.add('open'); backdrop.classList.add('open'); drawer.setAttribute('aria-hidden', 'false'); refreshMemory(); });
    byId('memory-close').addEventListener('click', closeDrawer); backdrop.addEventListener('click', closeDrawer);
    document.querySelectorAll('[data-memory-scope]').forEach((button) => button.addEventListener('click', () => { state.memoryScope = button.dataset.memoryScope; document.querySelectorAll('[data-memory-scope]').forEach((item) => item.classList.toggle('active', item === button)); renderMemoryKeys(); refreshMemory(); }));
    byId('memory-enabled').addEventListener('change', async (event) => { if (!event.target.checked) { try { await memoryRequest('POST', '/enabled', { domain_id: state.domain, enabled: false }); } catch (_) {} } else { try { await memoryRequest('POST', '/enabled', { domain_id: state.domain, enabled: true }); } catch (_) {} } refreshMemory(); });
    byId('memory-save').addEventListener('click', async () => { const key = byId('memory-key').value; const value = parseMemoryValue(byId('memory-value').value); await memoryRequest('PUT', '', { domain_id: state.domain, scope: state.memoryScope, preferences: { [key]: value }, explicitly_confirmed: true }); byId('memory-value').value = ''; await refreshMemory(); });
    byId('memory-clear').addEventListener('click', async () => { await memoryRequest('DELETE', '', { domain_id: state.domain, scope: state.memoryScope, fields: null }); await refreshMemory(); });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    bindEvents();
    byId('memory-identity').textContent = '默认关闭';
    try { await loadBundle(); } catch (error) { byId('result-panel').innerHTML = `<div class="empty-result"><h2>回放数据加载失败</h2><p>${esc(error.message)}</p></div>`; }
  });
})();
