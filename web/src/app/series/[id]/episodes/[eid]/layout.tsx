import { Metadata } from "next";

const API_HOST = process.env.API_HOST || "http://localhost:8000";

async function getEpisodeData(novelId: string, episodeId: string) {
  try {
    const res = await fetch(`${API_HOST}/api/series/${novelId}/episodes/${episodeId}`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string; eid: string }> }): Promise<Metadata> {
  const { id, eid } = await params;
  const data = await getEpisodeData(id, eid);
  const episode = data?.episode;
  const novel = data?.novel;
  if (!episode || !novel) return {};
  const title = `${episode.title} — ${novel.title} — WRIT`;
  const desc = (episode.content || "").replace(/<[^>]*>/g, "").slice(0, 200) || novel.description?.slice(0, 200) || "";
  const image = novel.cover_image || "/icons/icon-512.png";
  return {
    title,
    description: desc,
    openGraph: {
      title,
      description: desc,
      type: "article",
      images: [{ url: image }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description: desc,
      images: [image],
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
