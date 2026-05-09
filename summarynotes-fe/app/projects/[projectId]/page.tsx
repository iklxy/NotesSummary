import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import ProjectDetailClient from "./client";

interface Props {
  params: Promise<{
    projectId: string;
  }>;
}

export default async function ProjectDetailPage({ params }: Props) {
  const { projectId } = await params;
  const id = Number(projectId);
  const safeId = Number.isFinite(id) && id > 0 ? id : -1;
  const cookieStore = await cookies();
  if (!cookieStore.get("bh_user_id")?.value) {
    redirect(`/login?next=/projects/${safeId}`);
  }
  return <ProjectDetailClient projectId={safeId} />;
}
