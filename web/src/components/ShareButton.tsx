"use client";
import { useState } from "react";
import Icon from "./Icon";

export default function ShareButton({ url, className = "action-btn" }: { url: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    const fullUrl = url.startsWith("http") ? url : window.location.origin + url;
    try {
      await navigator.clipboard.writeText(fullUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = fullUrl;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <button onClick={handleClick} className={className} title={copied ? "복사됨!" : "링크 복사"}>
      <Icon name={copied ? "check" : "link"} />
    </button>
  );
}
