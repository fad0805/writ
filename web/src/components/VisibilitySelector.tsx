"use client";
import { useState } from "react";
import Icon from "./Icon";

export const VIS_OPTIONS = [
  { value: "public", label: "공개", icon: "globe" },
  { value: "home", label: "홈", icon: "home" },
  { value: "followers", label: "팔로워", icon: "lock" },
  { value: "mention", label: "멘션", icon: "mail" },
];

export const PUBLIC_OPTIONS = VIS_OPTIONS.slice(0, 3);

let uid = 0;

export default function VisibilitySelector({
  value, onChange, includeMention = false, className = "", name,
}: {
  value: string; onChange: (v: string) => void; includeMention?: boolean; className?: string; name?: string;
}) {
  const [groupName] = useState(() => name || `_vis_${++uid}`);
  const options = includeMention ? VIS_OPTIONS : PUBLIC_OPTIONS;
  return (
    <div className={`visibility-selector ${className}`}>
      {options.map((v) => (
        <label key={v.value}>
          <input type="radio" name={groupName} value={v.value} checked={value === v.value} onChange={() => onChange(v.value)} />
          <Icon name={v.icon} /> {v.label}
        </label>
      ))}
    </div>
  );
}
