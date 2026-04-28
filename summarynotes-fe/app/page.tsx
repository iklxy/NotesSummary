import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import HomeClient from "./page-client";

export default async function Home() {
  const cookieStore = await cookies();
  if (!cookieStore.get("bh_user_id")?.value) {
    redirect("/login?next=/");
  }

  return <HomeClient />;
}
