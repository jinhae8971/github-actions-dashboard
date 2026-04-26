"""Patch index.html with persistent light/dark theme controls.

This script is intentionally idempotent and should run after the other UI
patchers so the generated dashboard keeps the user's display preference.
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


text = insert_after_once(
    text,
    '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css" />\n',
    """<script>
  (() => {
    try {
      const pref = localStorage.getItem('gh_dashboard_theme') || 'system';
      const dark = pref === 'dark' || (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
      document.documentElement.dataset.theme = dark ? 'dark' : 'light';
      document.documentElement.dataset.themePreference = pref;
    } catch (e) {
      document.documentElement.dataset.theme = 'light';
      document.documentElement.dataset.themePreference = 'system';
    }
  })();
</script>
""",
)

text = insert_after_once(
    text,
    "    --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);\n  }\n",
    """
  [data-theme="dark"] {
    color-scheme: dark;
    --bg: #0b1120;
    --surface: #111827;
    --border: #273449;
    --text-primary: #e5e7eb;
    --text-secondary: #9ca3af;
    --text-tertiary: #6b7280;
    --success: #34d399;
    --success-light: rgba(16, 185, 129, 0.14);
    --error: #fb7185;
    --error-light: rgba(244, 63, 94, 0.14);
    --warning: #fbbf24;
    --warning-light: rgba(245, 158, 11, 0.14);
    --info: #fb923c;
    --info-light: rgba(249, 115, 22, 0.14);
    --primary: #60a5fa;
    --primary-light: rgba(59, 130, 246, 0.16);
    --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.35);
  }
""",
)

text = insert_after_once(
    text,
    "  .settings-btn:hover {\n    background: var(--bg);\n    color: var(--text-primary);\n    border-color: var(--primary);\n  }\n",
    """

  .theme-quick-btn {
    width: 34px;
    height: 34px;
    justify-content: center;
    padding: 0;
  }

  .theme-setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
  }

  .theme-segmented {
    display: inline-grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 4px;
    min-width: 220px;
  }

  .theme-option {
    border: 0;
    background: transparent;
    color: var(--text-secondary);
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }

  .theme-option:hover {
    color: var(--text-primary);
    background: var(--surface);
  }

  .theme-option.active {
    background: var(--surface);
    color: var(--primary);
    box-shadow: var(--shadow-sm);
  }
""",
)

text = text.replace(
    "    .header-right { width: 100%; justify-content: space-between; }\n"
    "    .last-updated { font-size: 11px; }\n"
    "    .header-right { flex-wrap: wrap; justify-content: flex-start; }\n"
    "    .last-updated { flex: 1 0 100%; }\n",
    "    .header-right { width: 100%; justify-content: flex-start; flex-wrap: wrap; }\n"
    "    .last-updated { flex: 1 0 100%; font-size: 11px; }\n",
)

text = replace_once_or_present(
    text,
    "    .header-right { width: 100%; justify-content: space-between; }\n"
    "    .last-updated { font-size: 11px; }\n",
    "    .header-right { width: 100%; justify-content: flex-start; flex-wrap: wrap; }\n"
    "    .last-updated { flex: 1 0 100%; font-size: 11px; }\n",
)

text = insert_after_once(
    text,
    "    .refresh-btn { padding: 8px 14px; font-size: 12px; min-height: 36px; }\n",
    "    .theme-quick-btn { width: 36px; min-width: 36px; padding: 0; }\n",
)

text = insert_after_once(
    text,
    "    .settings-modal { border-radius: 16px 16px 0 0; }\n",
    "    .theme-setting-row { align-items: flex-start; flex-direction: column; }\n    .theme-segmented { width: 100%; min-width: 0; }\n",
)

text = replace_once_or_present(
    text,
    '<button class="settings-btn" onclick="openSettings()" title="설정 (GitHub 토큰 · 일시 정지 관리)">⚙</button>',
    """<button class="settings-btn theme-quick-btn" id="themeToggleBtn" onclick="toggleTheme()" title="화면 모드 전환" aria-label="화면 모드 전환">
      <svg id="themeToggleIcon" width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <path d="M8 1.25a.75.75 0 0 1 .75.75v1a.75.75 0 0 1-1.5 0V2A.75.75 0 0 1 8 1.25Zm0 10a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Zm6.75-3.25a.75.75 0 0 1-.75.75h-1a.75.75 0 0 1 0-1.5h1a.75.75 0 0 1 .75.75ZM3.75 8a.75.75 0 0 1-.75.75H2a.75.75 0 0 1 0-1.5h1a.75.75 0 0 1 .75.75Zm7.773-4.773a.75.75 0 0 1 1.06 0l.708.707a.75.75 0 1 1-1.061 1.06l-.707-.707a.75.75 0 0 1 0-1.06Zm-8.814.707a.75.75 0 0 1 1.06-1.06l.708.707a.75.75 0 1 1-1.061 1.06l-.707-.707Zm9.521 7.073a.75.75 0 1 1 1.061 1.06l-.707.708a.75.75 0 1 1-1.061-1.06l.707-.708Zm-7.753 0a.75.75 0 0 1 0 1.06l-.707.708a.75.75 0 1 1-1.061-1.06l.707-.708a.75.75 0 0 1 1.061 0Z"/>
      </svg>
    </button>
    <button class="settings-btn" onclick="openSettings()" title="설정 (GitHub 토큰 · 일시 정지 관리 · 화면 모드)">⚙</button>""",
)

text = replace_once_or_present(
    text,
    '<div class="modal-meta"><span>GitHub 토큰 · 일시 정지 관리</span></div>',
    '<div class="modal-meta"><span>GitHub 토큰 · 일시 정지 관리 · 화면 모드</span></div>',
)

text = insert_after_once(
    text,
    """      <button class="modal-close" onclick="closeSettings()" title="닫기">✕</button>
    </div>

""",
    """    <!-- Display Settings -->
    <div class="settings-section">
      <div class="theme-setting-row">
        <div>
          <h3>화면 모드</h3>
          <p>이 브라우저에 저장됩니다. 시스템을 선택하면 OS 설정을 따릅니다.</p>
        </div>
        <div class="theme-segmented" role="group" aria-label="화면 모드">
          <button class="theme-option" data-theme-choice="system" onclick="setTheme('system')">시스템</button>
          <button class="theme-option" data-theme-choice="light" onclick="setTheme('light')">라이트</button>
          <button class="theme-option" data-theme-choice="dark" onclick="setTheme('dark')">다크</button>
        </div>
      </div>
    </div>

""",
)

text = insert_after_once(
    text,
    "const TOKEN_KEY = 'gh_dashboard_token';\n",
    "const THEME_KEY = 'gh_dashboard_theme';\n",
)

text = insert_after_once(
    text,
    "let lastPausedStateUpdatedAt = 0;\n",
    """
let themePreference = localStorage.getItem(THEME_KEY) || 'system';
const systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)');

function getResolvedTheme(pref = themePreference) {
  if (pref === 'dark' || pref === 'light') return pref;
  return systemThemeQuery.matches ? 'dark' : 'light';
}

function applyTheme(pref = themePreference) {
  themePreference = pref || 'system';
  const resolved = getResolvedTheme(themePreference);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = themePreference;
  updateThemeControls();
}

function setTheme(pref) {
  if (!['system', 'light', 'dark'].includes(pref)) pref = 'system';
  localStorage.setItem(THEME_KEY, pref);
  applyTheme(pref);
}

function toggleTheme() {
  setTheme(getResolvedTheme() === 'dark' ? 'light' : 'dark');
}

function updateThemeControls() {
  const resolved = getResolvedTheme();
  document.querySelectorAll('.theme-option').forEach(btn => {
    const active = btn.dataset.themeChoice === themePreference;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });

  const icon = document.getElementById('themeToggleIcon');
  const btn = document.getElementById('themeToggleBtn');
  if (icon) {
    icon.innerHTML = resolved === 'dark'
      ? '<path d="M6.2 1.28a.75.75 0 0 1 .96.9 5.38 5.38 0 0 0 6.66 6.66.75.75 0 0 1 .9.96A6.75 6.75 0 1 1 6.2 1.28ZM5.45 3.1a5.25 5.25 0 1 0 7.45 7.45A6.88 6.88 0 0 1 5.45 3.1Z"/>'
      : '<path d="M8 1.25a.75.75 0 0 1 .75.75v1a.75.75 0 0 1-1.5 0V2A.75.75 0 0 1 8 1.25Zm0 10a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Zm6.75-3.25a.75.75 0 0 1-.75.75h-1a.75.75 0 0 1 0-1.5h1a.75.75 0 0 1 .75.75ZM3.75 8a.75.75 0 0 1-.75.75H2a.75.75 0 0 1 0-1.5h1a.75.75 0 0 1 .75.75Zm7.773-4.773a.75.75 0 0 1 1.06 0l.708.707a.75.75 0 1 1-1.061 1.06l-.707-.707a.75.75 0 0 1 0-1.06Zm-8.814.707a.75.75 0 0 1 1.06-1.06l.708.707a.75.75 0 1 1-1.061 1.06l-.707-.707Zm9.521 7.073a.75.75 0 1 1 1.061 1.06l-.707.708a.75.75 0 1 1-1.061-1.06l.707-.708Zm-7.753 0a.75.75 0 0 1 0 1.06l-.707.708a.75.75 0 1 1-1.061-1.06l.707-.708a.75.75 0 0 1 1.061 0Z"/>';
  }
  if (btn) btn.title = resolved === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환';
}

systemThemeQuery.addEventListener?.('change', () => {
  if (themePreference === 'system') applyTheme('system');
});
applyTheme(themePreference);

""",
)

text = insert_after_once(
    text,
    "  document.getElementById('tokenInput').value = githubToken ? '••••••••••••••••••••' : '';\n",
    "  updateThemeControls();\n",
)

path.write_text(text, encoding="utf-8")
