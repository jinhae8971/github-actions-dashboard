"""Patch index.html with operations-health dashboard affordances.

This script is intentionally idempotent and runs after patch_dashboard_ui.py.
"""

from pathlib import Path


path = Path("index.html")
text = path.read_text(encoding="utf-8")


def insert_after_once(src, marker, addition):
    if addition.strip() in src:
        return src
    if marker not in src:
        raise SystemExit(f"marker not found: {marker}")
    return src.replace(marker, marker + addition, 1)


def replace_once_or_present(src, old, new):
    if old in src:
        return src.replace(old, new, 1)
    if new in src:
        return src
    raise SystemExit(f"marker not found: {old}")


def replace_between(src, start, end, replacement):
    start_idx = src.find(start)
    if start_idx == -1:
        raise SystemExit(f"start marker not found: {start}")
    end_idx = src.find(end, start_idx)
    if end_idx == -1:
        raise SystemExit(f"end marker not found after {start}: {end}")
    return src[:start_idx] + replacement + src[end_idx:]


text = insert_after_once(
    text,
    "  .badge.paused { background: var(--warning-light); color: var(--warning); }\n",
    "  .badge.stale { background: var(--warning-light); color: var(--warning); }\n"
    "  .badge.upstream { background: var(--info-light); color: var(--info); }\n"
    "  .badge.policy { background: var(--error-light); color: var(--error); }\n"
    "  .badge.intentional { background: var(--bg); color: var(--text-secondary); border: 1px solid var(--border); }\n"
    "\n"
    "  .ops-banner {\n"
    "    border-radius: 7px;\n"
    "    padding: 8px 12px;\n"
    "    margin-bottom: 12px;\n"
    "    font-size: 11px;\n"
    "    line-height: 1.45;\n"
    "    display: flex;\n"
    "    flex-direction: column;\n"
    "    gap: 3px;\n"
    "  }\n"
    "  .ops-banner.warning { background: var(--warning-light); color: var(--warning); border: 1px solid var(--warning); }\n"
    "  .ops-banner.error { background: var(--error-light); color: var(--error); border: 1px solid var(--error); }\n"
    "  .ops-banner.info { background: var(--info-light); color: var(--info); border: 1px solid var(--info); }\n",
)

text = replace_once_or_present(
    text,
    """      if (local) local.wf.state = 'active';
      toast(`▶ ${wfName} 재가동 완료`);""",
    """      if (local) {
        local.wf.state = 'active';
        local.health = { state: 'ok', label: '정상', severity: 0, reason: 'Workflow was resumed locally.' };
      }
      toast(`▶ ${wfName} 재가동 완료`);""",
)

text = replace_once_or_present(
    text,
    """      if (local) local.wf.state = 'disabled_manually';
      toast(`⏸ ${wfName} 일시 정지 완료`);""",
    """      if (local) {
        local.wf.state = 'disabled_manually';
        local.health = { state: 'paused_unexpected', label: '정책 불일치', severity: 2, reason: 'Workflow was paused locally; dashboard refresh is queued.' };
      }
      toast(`⏸ ${wfName} 일시 정지 완료`);""",
)

text = insert_after_once(
    text,
    "// ── Render Functions ─────────────────────────────────────────────────────\n",
    """function healthBadgeClass(state) {
  if (state === 'paused_expected') return 'intentional';
  if (state === 'paused_unexpected' || state === 'active_unexpected' || state === 'failing' || state === 'missing_report') return 'policy';
  if (state === 'upstream_degraded') return 'upstream';
  if (state === 'stale_run' || state === 'stale_report' || state === 'no_recent_run') return 'stale';
  return 'loading';
}

function healthBadgeHtml(item, paused, conclusion, badgeMap) {
  const health = item.health || {};
  const state = health.state || '';
  if (state && !['ok', 'running'].includes(state)) {
    return `<span class=\"badge ${healthBadgeClass(state)}\">${health.label || state}</span>`;
  }
  if (paused) return '<span class=\"badge paused\">⏸ 일시 정지</span>';
  return badgeMap[conclusion] || `<span class=\"badge loading\">${conclusion}</span>`;
}

function healthBannerHtml(item, paused) {
  const health = item.health || {};
  const state = health.state || '';
  if (!state || ['ok', 'running'].includes(state)) return '';

  const cls = health.severity >= 3 || state.includes('unexpected') || state === 'failing' || state === 'missing_report'
    ? 'error'
    : (state === 'upstream_degraded' ? 'info' : 'warning');
  const deps = item.upstream?.dependencies || [];
  const depText = deps.length
    ? `<span>의존성: ${deps.map(d => `${d.repo} ${d.fresh ? 'ok' : d.workflow_label}`).join(' · ')}</span>`
    : '';
  return `
    <div class=\"ops-banner ${cls}\">
      <strong>${health.label || '운영 상태 확인 필요'}</strong>
      <span>${health.reason || ''}</span>
      ${depText}
    </div>`;
}

""",
)

text = replace_between(
    text,
    "function renderSummary(wfData) {",
    "\n\nfunction renderWeekCalendar",
    """function renderSummary(wfData) {
  const pausedCount  = Object.keys(pausedMap).length;
  const total        = wfData.length;
  const healthCounts = wfData.reduce((acc, d) => {
    const state = d.health?.state || 'unknown';
    acc[state] = (acc[state] || 0) + 1;
    return acc;
  }, {});
  const okCount = (healthCounts.ok || 0) + (healthCounts.running || 0) + (healthCounts.paused_expected || 0);
  const attentionCount = wfData.filter(d => (d.health?.severity || 0) >= 2).length;
  const policyMismatch = (healthCounts.paused_unexpected || 0) + (healthCounts.active_unexpected || 0);
  const staleCount = (healthCounts.stale_run || 0) + (healthCounts.stale_report || 0) +
    (healthCounts.no_recent_run || 0) + (healthCounts.upstream_degraded || 0) + (healthCounts.missing_report || 0);

  document.getElementById('summaryCards').innerHTML = `
    <div class=\"stat-card\"><div class=\"val blue\">${total}</div><div class=\"lbl\">전체 워크플로우</div></div>
    <div class=\"stat-card\"><div class=\"val green\">${okCount}</div><div class=\"lbl\">정상/의도정지</div></div>
    <div class=\"stat-card\" style=\"border-color:${attentionCount ? 'var(--warning)' : 'var(--border)'}\">
      <div class=\"val ${attentionCount ? 'yellow' : 'green'}\">${attentionCount}</div><div class=\"lbl\">주의 필요</div>
    </div>
    <div class=\"stat-card\" style=\"border-color:${policyMismatch ? 'var(--error)' : 'var(--border)'}\">
      <div class=\"val ${policyMismatch ? 'red' : 'purple'}\">${policyMismatch || pausedCount || staleCount}</div>
      <div class=\"lbl\">${policyMismatch ? '정책 불일치' : (pausedCount ? '일시 정지 중' : '지연/의존성')}</div>
    </div>
  `;
}""",
)

text = replace_once_or_present(
    text,
    "  const cards = wfData.map(({ repo, wf, cron, runs }) => {",
    "  const cards = wfData.map((item) => {\n    const { repo, wf, cron, runs } = item;",
)

text = replace_once_or_present(
    text,
    """    const badge    = paused
      ? '<span class="badge paused">⏸ 일시 정지</span>'
      : (badgeMap[conclusion] || `<span class="badge loading">${conclusion}</span>`);""",
    "    const badge    = healthBadgeHtml(item, paused, conclusion, badgeMap);",
)

text = replace_once_or_present(
    text,
    """    const pausedBanner = paused ? `
      <div class="paused-banner">
        ⏸ 이 워크플로우는 현재 일시 정지 중입니다. 재가동 버튼을 누르면 다시 실행됩니다.
      </div>` : '';""",
    """    const pausedBanner = healthBannerHtml(item, paused) || (paused ? `
      <div class="paused-banner">
        ⏸ 이 워크플로우는 현재 일시 정지 중입니다. 재가동 버튼을 누르면 다시 실행됩니다.
      </div>` : '');""",
)

path.write_text(text, encoding="utf-8")
