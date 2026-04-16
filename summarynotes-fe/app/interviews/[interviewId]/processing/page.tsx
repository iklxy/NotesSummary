import InterviewProcessingClient from "./client";

interface Props {
  params: Promise<{
    interviewId: string;
  }>;
}

export default async function InterviewProcessingPage({ params }: Props) {
  const { interviewId } = await params;
  const id = Number(interviewId);
  const safeId = Number.isFinite(id) && id > 0 ? id : -1;
  return <InterviewProcessingClient interviewId={safeId} />;
}
