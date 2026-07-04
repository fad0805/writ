(function() {
  var t = localStorage.getItem('theme');
  if (t === 'dark') { document.body.className = 'dark-theme'; }
  var moonSvg = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>';
  var sunSvg = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
  function setTheme(dark) {
    document.body.classList.toggle('dark-theme', dark);
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    var b = document.querySelector('.theme-toggle');
    if (b) b.innerHTML = (dark ? sunSvg : moonSvg) + ' ' + (dark ? '\uB77C\uC774\uD2B8\uBAA8\uB4DC' : '\uB2E4\uD06C\uBAA8\uB4DC');
  }
  var b = document.querySelector('.theme-toggle');
  if (b) {
    setTheme(t === 'dark');
    b.onclick = function() { setTheme(!document.body.className.includes('dark')); };
  }
  function isTypingTarget(target) {
    return target && target.closest && target.closest('input,textarea,select,button,a');
  }
  function showShortcutHelp() {
    var modal = document.getElementById('shortcut-help-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'shortcut-help-modal';
      modal.className = 'shortcut-help-backdrop';
      modal.innerHTML = '<div class="shortcut-help" onclick="event.stopPropagation()"><button type="button" class="shortcut-help-close" aria-label="닫기">×</button><h3>단축키</h3><dl><dt>n</dt><dd>새 글 작성으로 이동</dd><dt>d</dt><dd>테마 변경</dd><dt>?</dt><dd>단축키 보기</dd></dl></div>';
      modal.onclick = hideShortcutHelp;
      modal.querySelector('.shortcut-help-close').onclick = hideShortcutHelp;
      document.body.appendChild(modal);
    }
    modal.classList.add('active');
  }
  function hideShortcutHelp() {
    var modal = document.getElementById('shortcut-help-modal');
    if (modal) modal.classList.remove('active');
  }
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideShortcutHelp();
    if (e.ctrlKey || e.metaKey || isTypingTarget(e.target)) return;
    if (e.key === 'd') {
      setTheme(!document.body.className.includes('dark'));
    } else if (e.key === 'n') {
      var postContent = document.getElementById('post-content');
      if (postContent) {
        e.preventDefault();
        postContent.focus();
      }
    } else if (e.key === '?') {
      e.preventDefault();
      showShortcutHelp();
    }
  });
})();
