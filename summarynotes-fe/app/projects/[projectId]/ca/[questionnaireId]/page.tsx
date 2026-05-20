import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import CaQuestionnaireClient from "./client";

interface Props {
  params: Promise<{
    projectId: string;
    questionnaireId: string;
  }>;
}

export default async function CaQuestionnairePage({ params }: Props) {
  const { projectId, questionnaireId } = await params;
  const projectIdNum = Number(projectId);
  const questionnaireIdNum = Number(questionnaireId);
  const safeProjectId = Number.isFinite(projectIdNum) && projectIdNum > 0 ? projectIdNum : -1;
  const safeQuestionnaireId = Number.isFinite(questionnaireIdNum) && questionnaireIdNum > 0 ? questionnaireIdNum : -1;
  const cookieStore = await cookies();
  if (!cookieStore.get("bh_user_id")?.value) {
    redirect(`/login?next=/projects/${safeProjectId}/ca/${safeQuestionnaireId}`);
  }
  return <CaQuestionnaireClient projectId={safeProjectId} questionnaireId={safeQuestionnaireId} />;
}
