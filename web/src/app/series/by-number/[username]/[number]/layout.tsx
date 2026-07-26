import { Metadata } from "next";

const API_HOST = process.env.API_HOST || "http://localhost:8000";

async function getSeriesData(username: string, number: string) {
  try {
    const lookup = await fetch(`${API_HOST}/api/by-series-number/${username}/${number}`, { next: { revalidate: 60 } });
    if (!lookup.ok) return null;
    const brief = await lookup.json();
    if (!brief.id) return null;
    const full = await fetch(`${API_HOST}/api/series/${brief.id}`, { next: { revalidate: 60 } });
    if (!full.ok) return null;
    return await full.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ username: string; number: string }> }): Promise<Metadata> {
  const { username, number } = await params;
  const data = await getSeriesData(username, number);
  const novel = data?.novel;
  if (!novel) return {};
  const title = `${novel.title} — WRIT`;
  const desc = (novel.description || "").slice(0, 200);
  const image = novel.cover_image || "/icons/icon-512.png";
  return {
    title,
    description: desc,
    openGraph: {
      title,
      description: desc,
      type: "website",
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
