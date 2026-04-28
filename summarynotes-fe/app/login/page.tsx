import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { Spin } from "antd";
import LoginClient from "./login-client";

export default async function LoginPage() {
  const cookieStore = await cookies();
  if (cookieStore.get("bh_user_id")?.value) {
    redirect("/");
  }

  return (
    <Suspense
      fallback={
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background:
              "radial-gradient(circle at top, rgba(56,189,248,0.16), transparent 28%), linear-gradient(180deg, #f8fafc 0%, #eef4fb 100%)",
          }}
        >
          <Spin size="large" />
        </div>
      }
    >
      <LoginClient />
    </Suspense>
  );
}
