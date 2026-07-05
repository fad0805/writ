"use client";
import { useState } from "react";
import Icon from "./Icon";

export const SERIES_VIS_OPTIONS = [
  { value: "public", label: "전체공개", icon: "globe" },
  { value: "unlisted", label: "공개", icon: "eye" },
  { value: "private", label: "비공개", icon: "lock" },
];

let uid = 0;

export default function SeriesVisibilitySelector({
  value, onChange, className = "", name,
}: {
  value: string; onChange: (v: string) => void; className?: string; name?: string;
}) {
  const [groupName] = useState(() => name || `_series_vis_${++uid}`);
  return (
    <div className={`visibility-selector ${className}`}>
      {SERIES_VIS_OPTIONS.map((v) => (
        <label key={v.value}>
          <input type="radio" name={groupName} value={v.value} checked={value === v.value} onChange={() => onChange(v.value)} />
          <Icon name={v.icon} /> {v.label}
        </label>
      ))}
    </div>
  );
}
