"use client";
import { useState } from "react";
import Icon from "./Icon";

export const SERIES_STATUS_OPTIONS = [
  { value: "ongoing", label: "연재중", icon: "edit" },
  { value: "hiatus", label: "휴재", icon: "moon" },
  { value: "discontinued", label: "연재중단", icon: "x" },
  { value: "completed", label: "완결", icon: "check" },
];

let uid = 0;

export default function SeriesStatusSelector({
  value, onChange, className = "", name,
}: {
  value: string; onChange: (v: string) => void; className?: string; name?: string;
}) {
  const [groupName] = useState(() => name || `_series_status_${++uid}`);
  return (
    <div className={`visibility-selector ${className}`}>
      {SERIES_STATUS_OPTIONS.map((v) => (
        <label key={v.value}>
          <input type="radio" name={groupName} value={v.value} checked={value === v.value} onChange={() => onChange(v.value)} />
          <Icon name={v.icon} /> {v.label}
        </label>
      ))}
    </div>
  );
}
