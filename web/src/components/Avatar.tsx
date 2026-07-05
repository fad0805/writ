"use client";
import { avatarColor } from "@/lib/avatar";
import type { User } from "@/lib/api";

type Props = {
  user: User;
  className?: string;
  style?: React.CSSProperties;
};

export default function Avatar({ user, className, style }: Props) {
  if (user.avatar) {
    return <img src={user.avatar} alt="" className={className} style={{ objectFit: "cover", ...style }} />;
  }
  return (
    <div className={className} style={{ backgroundColor: avatarColor(user.username), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: "bold", ...style }}>
      {(user.display_name || user.username)[0]}
    </div>
  );
}
