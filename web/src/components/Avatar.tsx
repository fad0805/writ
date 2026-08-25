"use client";
import React, { useState } from "react";
import { avatarColor } from "@/lib/avatar";
import type { User } from "@/lib/api";

type Props = {
  user: User;
  className?: string;
  style?: React.CSSProperties;
};

export default React.memo(function Avatar({ user, className, style }: Props) {
  const [imgError, setImgError] = useState<string | null>(null);

  if (user.avatar && imgError !== user.avatar) {
    return <img key={user.avatar} src={user.avatar} alt="" className={className} style={{ objectFit: "cover", ...style }} onError={() => setImgError(user.avatar)} />;
  }
  return (
    <div className={className} style={{ backgroundColor: avatarColor(user.username), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", ...style }}>
      {(user.display_name || user.username)[0]}
    </div>
  );
});
