const COPY_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
const CHECK_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';

function installCopyButton(el: HTMLElement, text: string) {
  if (el.querySelector(".code-copy-btn")) return;
  const btn = document.createElement("button");
  btn.className = "code-copy-btn";
  btn.innerHTML = COPY_ICON;
  btn.onclick = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      btn.innerHTML = CHECK_ICON;
      setTimeout(() => { btn.innerHTML = COPY_ICON; }, 1500);
    } catch {
      btn.innerHTML = COPY_ICON;
    }
  };
  el.appendChild(btn);
}

export function installCodeCopyButtons(container: HTMLElement) {
  if (container.closest(".episode-editor-content")) return;

  container.querySelectorAll("pre").forEach((pre) => {
    const code = pre.querySelector("code");
    installCopyButton(pre, (code || pre).textContent || "");
  });

  container.querySelectorAll("code").forEach((code) => {
    if (code.closest("pre")) return;
    installCopyButton(code, code.textContent || "");
  });
}
