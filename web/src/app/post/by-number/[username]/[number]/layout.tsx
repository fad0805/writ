import { Metadata } from "next";

const API_HOST = process.env.API_HOST || "http://localhost:8000";

async function getPostData(username: string, number: string) {
  try {
    const res = await fetch(`${API_HOST}/api/by-number/${username}/${number}`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: { username: string; number: string } }): Promise<Metadata> {
  const data = await getPostData(params.username, params.number);
  if (!data) return {};
  const displayName = data.author?.display_name || data.author?.username || "WRIT";
  const content = (data.content || "").replace(/<[^>]*>/g, "").slice(0, 200);
  const media = data.media_attachments?.[0];
  const image = media?.url || "/icons/icon-512.png";
  return {
    title: `${displayName} — WRIT`,
    description: content,
    openGraph: {
      title: `${displayName} — WRIT`,
      description: content,
      type: "article",
      images: [{ url: image }],
    },
    twitter: {
      card: "summary_large_image",
      title: `${displayName} — WRIT`,
      description: content,
      images: [image],
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
