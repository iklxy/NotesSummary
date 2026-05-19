import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import OverallNotesCardsSection from "../../../../../components/OverallNotesCardsSection";
import type { InterviewOverallNotesResponse } from "../../../../../lib/types";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{
    interviewId: string;
  }>;
}

function getApiBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (value) {
    return value.replace(/\/$/, "");
  }
  return "http://127.0.0.1:9000";
}

function buildCookieHeader(cookieStore: Awaited<ReturnType<typeof cookies>>): string {
  return cookieStore
    .getAll()
    .map((item) => `${item.name}=${item.value}`)
    .filter(Boolean)
    .join("; ");
}

async function fetchOverallNotes(interviewId: number, cookieHeader: string): Promise<InterviewOverallNotesResponse> {
  const response = await fetch(`${getApiBaseUrl()}/api/interviews/${interviewId}/overall-notes`, {
    headers: {
      cookie: cookieHeader,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`load overall notes failed: ${response.status}`);
  }
  return (await response.json()) as InterviewOverallNotesResponse;
}

export default async function OverallNotesExportPreviewPage({ params }: Props) {
  const { interviewId } = await params;
  const id = Number(interviewId);
  const safeId = Number.isFinite(id) && id > 0 ? id : -1;
  const cookieStore = await cookies();
  if (!cookieStore.get("bh_user_id")?.value) {
    redirect(`/login?next=/interviews/${safeId}/overall-notes/export-preview`);
  }

  const data = await fetchOverallNotes(safeId, buildCookieHeader(cookieStore));
  const cards = data.cards?.items ?? [];

  return (
    <div className="summarynotes-card-export-shell">
      <OverallNotesCardsSection items={cards} />
    </div>
  );
}
