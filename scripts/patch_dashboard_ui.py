from pathlib import Path


path = Path("index.html")
text = path.read_text(encoding="utf-8")


def replace_between(src, start, end, replacement):
    start_idx = src.find(start)
    if start_idx == -1:
        raise SystemExit(f"start marker not found: {start}")
    end_idx = src.find(end, start_idx)
    if end_idx == -1:
        raise SystemExit(f"end marker not found after {start}: {end}")
    return src[:start_idx] + replacement + src[end_idx:]


def replace_once(src, old, new):
    if old not in src:
        raise SystemExit(f"marker not found: {old}")
    return src.replace(old, new, 1)


def insert_after_once(src, marker, addition):
    if addition.strip() in src:
        return src
    if marker not in src:
        raise SystemExit(f"marker not found: {marker}")
    return src.replace(marker, marker + addition, 1)


text = text.replace(
    "GitHub Actions Dashboard · jinhae8971 · 매시간 자동 갱신",
    "GitHub Actions Dashboard · jinhae8971 · 매일 07:30 KST 자동 갱신",
)

text = insert_after_once(
    text,
    "  'global-market-orchestrator': './data/reports/global-market-orchestrator_latest.json',\n",
    "  'crypto-cycle-intelligence': './data/reports/crypto-cycle-intelligence_latest.json',\n"
    "  'ai-semi-cycle-intelligence': './data/reports/ai-semi-cycle-intelligence_latest.json',\n"
    "  'cycle-intelligence-hub': './data/reports/cycle-intelligence-hub_latest.json',\n",
)

text = insert_after_once(
    text,
    "    'etf-strategist':            '📈',\n",
    "    'crypto-monitor':            '🪙',\n"
    "    'crypto-research-agent':     '🚀',\n"
    "    'kospi-research-agent':      '🇰🇷',\n"
    "    'sp500-research-agent':      '🇺🇸',\n"
    "    'nasdaq-research-agent':     '💻',\n"
    "    'dow30-research-agent':      '🏛️',\n"
    "    'global-market-orchestrator':'🌐',\n"
    "    'crypto-cycle-intelligence': '₿',\n"
    "    'ai-semi-cycle-intelligence':'🤖',\n"
    "    'cycle-intelligence-hub':    '🏛️',\n",
)

text = insert_after_once(
    text,
    "    'global-market-orchestrator': 'https://jinhae8971.github.io/global-market-orchestrator/',\n",
    "    // Cycle Intelligence ecosystem\n"
    "    'crypto-cycle-intelligence': 'https://jinhae8971.github.io/crypto-cycle-intelligence/',\n"
    "    'ai-semi-cycle-intelligence':'https://jinhae8971.github.io/ai-semi-cycle-intelligence/',\n"
    "    'cycle-intelligence-hub':    'https://jinhae8971.github.io/cycle-intelligence-hub/',\n",
)

text = insert_after_once(
    text,
    "let pauseDirtyUntil = Number(localStorage.getItem(PAUSE_DIRTY_KEY) || '0');\n",
    "let lastPausedStateUpdatedAt = 0;\n",
)

text = replace_between(
    text,
    "async function savePauseState() {",
    "\n\n// ── Cross-device Pause State Sync",
    """async function savePauseState() {
  try { localStorage.setItem(PAUSE_KEY, JSON.stringify(pausedMap)); } catch(e) {}
  markPauseDirty();  // 저장 완료 전까지 repo 덮어쓰기 방지
  const saved = await savePausedStateToRepo();
  if (saved) clearPauseDirty();  // repo 저장 성공 시 dirty 해제
  return saved;
}""",
)

text = replace_between(
    text,
    "function utf8ToBase64(str) {",
    "\n\n// Load paused.json",
    """function utf8ToBase64(str) {
  const bytes = new TextEncoder().encode(str);
  let binary = '';
  bytes.forEach(b => binary += String.fromCharCode(b));
  return btoa(binary);
}

function base64ToUtf8(b64) {
  const binary = atob(String(b64 || '').replace(/\s/g, ''));
  const bytes = Uint8Array.from(binary, ch => ch.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}""",
)

text = replace_between(
    text,
    "async function loadPausedStateFromRepo() {",
    "\n\n// Save pausedMap to repo",
    """async function loadPausedStateFromRepo() {
  try {
    // dirty 상태면 로컬 변경이 repo에 아직 반영 안 됐을 수 있으므로 스킵
    if (isPauseDirty()) {
      console.log('[paused.json] local dirty — repo 덮어쓰기 스킵 (', Math.round((pauseDirtyUntil - Date.now())/1000), 's left)');
      return;
    }

    let data = null;

    // 토큰이 있으면 GitHub API에서 최신 파일을 직접 읽어 Pages CDN 캐시를 우회
    if (githubToken) {
      try {
        const apiResp = await fetch(
          `https://api.github.com/repos/${PAUSE_REPO_FULL}/contents/${PAUSE_REPO_PATH}?ref=main`,
          {
            headers: {
              'Authorization': `token ${githubToken}`,
              'Accept': 'application/vnd.github+json',
              'X-GitHub-Api-Version': '2022-11-28',
            },
          }
        );
        if (apiResp.ok) {
          const envelope = await apiResp.json();
          if (envelope.content) data = JSON.parse(base64ToUtf8(envelope.content));
        }
      } catch(e) {
        console.log('[paused.json] API fetch failed, fallback to static file:', e);
      }
    }

    // 토큰이 없거나 API 실패 시 정적 파일 fallback
    if (!data) {
      const resp = await fetch(`./${PAUSE_REPO_PATH}?_=${Date.now()}`);
      if (!resp.ok) return;
      data = await resp.json();
    }

    const repoPaused = data.paused || {};
    lastPausedStateUpdatedAt = Date.parse(data.updated_at || '') || 0;

    // Use repo as master source, unless a local write is still dirty.
    Object.keys(pausedMap).forEach(id => delete pausedMap[id]);
    Object.assign(pausedMap, repoPaused);
    try { localStorage.setItem(PAUSE_KEY, JSON.stringify(pausedMap)); } catch(e) {}

    console.log('[paused.json] repo state loaded —', Object.keys(repoPaused).length, 'paused');
  } catch(e) {
    console.log('[paused.json] load failed, localStorage kept:', e);
  }
}""",
)

text = replace_between(
    text,
    "async function savePausedStateToRepo() {",
    "\n\n// ── GitHub API Calls",
    """async function savePausedStateToRepo() {
  if (!githubToken) return false;
  try {
    const savedAt = new Date().toISOString();
    const content = JSON.stringify({ updated_at: savedAt, paused: pausedMap }, null, 2);
    const b64 = utf8ToBase64(content);

    async function putWithLatestSha() {
      let sha = null;
      try {
        const r = await fetch(
          `https://api.github.com/repos/${PAUSE_REPO_FULL}/contents/${PAUSE_REPO_PATH}?ref=main`,
          {
            headers: {
              'Authorization': `token ${githubToken}`,
              'Accept': 'application/vnd.github+json',
              'X-GitHub-Api-Version': '2022-11-28',
            },
          }
        );
        if (r.ok) sha = (await r.json()).sha;
      } catch(e) {}

      const body = { message: 'chore: sync pause state', content: b64, branch: 'main', ...(sha ? { sha } : {}) };
      return fetch(
        `https://api.github.com/repos/${PAUSE_REPO_FULL}/contents/${PAUSE_REPO_PATH}`,
        {
          method: 'PUT',
          headers: {
            'Authorization': `token ${githubToken}`,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(body),
        }
      );
    }

    let resp = await putWithLatestSha();
    if (resp.status === 409) resp = await putWithLatestSha();

    const ok = resp.ok || resp.status === 200 || resp.status === 201;
    if (ok) lastPausedStateUpdatedAt = Date.parse(savedAt) || Date.now();
    return ok;
  } catch(e) {
    console.error('[paused.json] save failed:', e);
    return false;
  }
}""",
)

text = insert_after_once(
    text,
    """async function enableWorkflow(repo, wfId) {
  return githubApiCall(`/repos/${OWNER}/${repo}/actions/workflows/${wfId}/enable`);
}
""",
    """
async function triggerDashboardRefresh(silent = true) {
  if (!githubToken) return false;
  try {
    const resp = await fetch(
      `https://api.github.com/repos/${PAUSE_REPO_FULL}/actions/workflows/update-data.yml/dispatches`,
      {
        method: 'POST',
        headers: {
          'Authorization': `token ${githubToken}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ref: 'main' }),
      }
    );
    if (resp.status === 204) {
      if (!silent) toast('🚀 데이터 수집 시작됨 — 약 30~60초 후 자동 반영됩니다');
      return true;
    }
    const errData = await resp.json().catch(() => ({}));
    if (!silent) toast(`❌ 갱신 실패 (${resp.status}): ${errData.message || '알 수 없는 오류'}`, true);
    return false;
  } catch(e) {
    if (!silent) toast(`❌ 갱신 실패: ${e.message}`, true);
    return false;
  }
}
""",
)

text = replace_between(
    text,
    "async function togglePause(repo, wfId, wfName) {",
    "\n\n// ── Settings Modal",
    """async function togglePause(repo, wfId, wfName) {
  const id = String(wfId);
  const btn = document.getElementById(`pbtn-${id}`);

  // 토큰 없으면 실제 제어 불가 → 설정 안내
  if (!githubToken) {
    toast('🔑 설정(⚙️)에서 GitHub 토큰을 먼저 등록해 주세요', true);
    openSettings();
    return;
  }

  if (btn) btn.classList.add('loading-state');

  try {
    const wasPaused = isPaused(id);
    const result = wasPaused
      ? await enableWorkflow(repo, wfId)
      : await disableWorkflow(repo, wfId);

    if (!result.ok) {
      const msg = result.status === 403
        ? '🔑 토큰에 repo 권한이 없습니다. 설정에서 토큰을 재발급해 주세요.'
        : `❌ GitHub API 오류 (${result.status}) — ${wasPaused ? '재가동' : '일시 정지'} 실패`;
      toast(msg, true);
      if (result.status === 403) openSettings();
      return;
    }

    const local = allWorkflows.find(d => String(d.wf.id) === id);
    if (wasPaused) {
      delete pausedMap[id];
      if (local) local.wf.state = 'active';
      toast(`▶ ${wfName} 재가동 완료`);
    } else {
      pausedMap[id] = { repo, name: wfName, updated_at: new Date().toISOString() };
      if (local) local.wf.state = 'disabled_manually';
      toast(`⏸ ${wfName} 일시 정지 완료`);
    }

    const saved = await savePauseState();
    if (!saved) {
      toast('⚠ GitHub 동작은 완료됐지만 paused.json 저장이 실패했습니다. 토큰 권한을 확인해 주세요.', true);
    }

    renderCards(allWorkflows);
    renderWeekCalendar(allWorkflows);
    renderSummary(allWorkflows);
    refreshPauseList();

    // GitHub 실제 상태가 바뀌었으므로 dashboard snapshot도 바로 갱신
    triggerDashboardRefresh(true);
  } finally {
    if (btn) btn.classList.remove('loading-state');
  }
}""",
)

text = replace_between(
    text,
    "async function saveToken() {",
    "\n\nfunction clearToken",
    """async function saveToken() {
  const raw = document.getElementById('tokenInput').value.trim();
  if (!raw || raw === '••••••••••••••••••••') {
    setTokenStatus('info', '⚠ 새 토큰을 입력해 주세요.');
    return;
  }
  githubToken = raw;
  localStorage.setItem(TOKEN_KEY, githubToken);
  setTokenStatus('info', '⏳ 연결 확인 중...');

  // Test authentication + scope check
  try {
    const resp = await fetch('https://api.github.com/user', {
      headers: {
        'Authorization': `token ${githubToken}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      }
    });
    if (resp.ok) {
      const data = await resp.json();
      const scopesRaw = (resp.headers.get('x-oauth-scopes') || '').toLowerCase();
      const scopes = scopesRaw.split(',').map(s => s.trim()).filter(Boolean);
      if (!scopesRaw) {
        setTokenStatus('info',
          `ℹ 연결 성공! (${data.login}) — 권한 헤더를 확인할 수 없습니다. ` +
          `일시정지/재가동이 실패하면 repo 및 workflow 권한을 확인해 주세요.`);
        return;
      }

      const missing = [];
      if (!scopes.includes('repo')) missing.push('repo');
      if (!scopes.includes('workflow')) missing.push('workflow');

      if (missing.length === 0) {
        setTokenStatus('ok', `✅ 연결 성공! (${data.login}) — repo/workflow 권한 확인됨`);
      } else {
        setTokenStatus('err',
          `⚠️ 연결됨 (${data.login}) 그러나 ${missing.join(', ')} 권한 없음!\n` +
          `일시정지/재가동 및 데이터 즉시 갱신에는 repo + workflow scope가 필요합니다.\n` +
          `GitHub → Settings → Tokens에서 repo, workflow 체크 후 재발급해 주세요.`);
      }
    } else {
      setTokenStatus('err', `❌ 인증 실패 (HTTP ${resp.status}) — 토큰을 확인해 주세요.`);
    }
  } catch(e) {
    setTokenStatus('err', `❌ 네트워크 오류: ${e.message}`);
  }
}""",
)

text = replace_between(
    text,
    "// ── GitHub Actions Manual Data Update",
    "\n\n// ── Sync Pause State from JSON",
    """// ── GitHub Actions Manual Data Update ──────────────────────────────────

async function fetchLatestData() {
  const btn = document.getElementById('fetchBtn');
  if (!githubToken) {
    toast('⚙ 설정에서 GitHub 토큰을 먼저 입력해주세요.', true);
    return;
  }
  btn.disabled = true;
  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" class="spin"><path d="M8 3a5 5 0 1 0 4.546 2.914.5.5 0 0 1 .908-.417A6 6 0 1 1 8 2v1z"/><path d="M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966c.12.1.12.284 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466z"/></svg> 수집 중…`;

  const triggered = await triggerDashboardRefresh(false);
  if (triggered) {
    setTimeout(async () => {
      await loadAll();
      btn.disabled = false;
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M1.5 1.5A.5.5 0 0 1 2 1h4a.5.5 0 0 1 0 1H3.707l2.147 2.146a.5.5 0 1 1-.708.708L3 2.707V4.5a.5.5 0 0 1-1 0v-3zm9 9a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V12.293l-2.146 2.147a.5.5 0 0 1-.708-.708L13.293 11.5H11.5a.5.5 0 0 1-.5-.5z"/><path d="M8 1a7 7 0 1 0 4.95 11.95.5.5 0 1 0-.707-.707A6 6 0 1 1 8 2v1z"/></svg> 데이터 갱신`;
    }, 35000);
  } else {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M1.5 1.5A.5.5 0 0 1 2 1h4a.5.5 0 0 1 0 1H3.707l2.147 2.146a.5.5 0 1 1-.708.708L3 2.707V4.5a.5.5 0 0 1-1 0v-3zm9 9a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V12.293l-2.146 2.147a.5.5 0 0 1-.708-.708L13.293 11.5H11.5a.5.5 0 0 1-.5-.5z"/><path d="M8 1a7 7 0 1 0 4.95 11.95.5.5 0 1 0-.707-.707A6 6 0 1 1 8 2v1z"/></svg> 데이터 갱신`;
  }
}""",
)

text = replace_between(
    text,
    "function syncPauseStateFromJson(wfData) {",
    "\n\n// ── Data Load",
    """function syncPauseStateFromJson(wfData, snapshotUpdatedAt = 0) {
  let changed = false;
  const allowRemovals = !isPauseDirty() && (
    !lastPausedStateUpdatedAt || !snapshotUpdatedAt || snapshotUpdatedAt >= lastPausedStateUpdatedAt
  );
  const currentIds = new Set(wfData.map(({ wf }) => String(wf.id)));

  if (allowRemovals) {
    Object.keys(pausedMap).forEach(id => {
      if (!currentIds.has(id)) {
        delete pausedMap[id];
        changed = true;
      }
    });
  }

  wfData.forEach(({ repo, wf }) => {
    const id = String(wf.id);
    const disabledOnGitHub = wf.state === 'disabled_manually' || wf.state === 'disabled_inactivity';

    if (disabledOnGitHub) {
      if (!pausedMap[id] || pausedMap[id].repo !== repo || pausedMap[id].name !== wf.name) {
        pausedMap[id] = { repo, name: wf.name };
        changed = true;
      }
      return;
    }

    if (allowRemovals && pausedMap[id]) {
      delete pausedMap[id];
      changed = true;
    }
  });

  if (changed) {
    try { localStorage.setItem(PAUSE_KEY, JSON.stringify(pausedMap)); } catch(e) {}
    savePausedStateToRepo().then(saved => {
      if (!saved) console.log('[paused.json] reconciled locally, repo save skipped or failed');
    });
  }
}""",
)

text = replace_once(
    text,
    "    syncPauseStateFromJson(allWorkflows);  // Then sync GitHub actual disabled state",
    "    syncPauseStateFromJson(allWorkflows, Date.parse(data.updated_at || '') || 0);  // Then sync GitHub actual disabled state",
)

path.write_text(text, encoding="utf-8")
