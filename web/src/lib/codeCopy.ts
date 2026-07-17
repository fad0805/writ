function installCopyButton(el: HTMLElement, text: string) {
  if (el.querySelector(".code-copy-btn")) return;
  const btn = document.createElement("button");
  btn.className = "code-copy-btn";
  btn.textContent = "Copy";
  btn.onclick = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    } catch {
      btn.textContent = "Failed";
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
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
