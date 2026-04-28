import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import InterviewDetailClient from "./client";

interface Props {
  params: Promise<{
    interviewId: string;
  }>;
}

export default async function InterviewDetailPage({ params }: Props) {
  const { interviewId } = await params;
  const id = Number(interviewId);
  const safeId = Number.isFinite(id) && id > 0 ? id : -1;
  const cookieStore = await cookies();
  if (!cookieStore.get("bh_user_id")?.value) {
    redirect(`/login?next=/interviews/${safeId}`);
  }
  return <InterviewDetailClient interviewId={safeId} />;
}
