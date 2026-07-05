"use client";
import { useState } from "react";
import { avatarColor } from "@/lib/avatar";
import type { User } from "@/lib/api";

type Props = {
  user: User;
  className?: string;
  style?: React.CSSProperties;
};

export default function Avatar({ user, className, style }: Props) {
  const [imgError, setImgError] = useState(false);

  if (user.avatar && !imgError) {
    return <img key={user.avatar} src={user.avatar} alt="" className={className} style={{ objectFit: "cover", ...style }} onError={() => setImgError(true)} />;
  }
  return (
    <div className={className} style={{ backgroundColor: avatarColor(user.username), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", ...style }}>
      {(user.display_name || user.username)[0]}
    </div>
  );
}
