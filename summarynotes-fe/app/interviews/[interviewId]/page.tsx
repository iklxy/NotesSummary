import InterviewDetailClient from "./client";

interface Props {
  params: {
    interviewId: string;
  };
}

export default function InterviewDetailPage({ params }: Props) {
  const id = Number(params.interviewId);
  const safeId = Number.isFinite(id) && id > 0 ? id : -1;
  return <InterviewDetailClient interviewId={safeId} />;
}
