import { NextRequest, NextResponse } from "next/server";

function getBackendBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (value) {
    return value.replace(/\/$/, "");
  }
  return "http://127.0.0.1:9000";
}

export async function GET(
  request: NextRequest,
  context: { params: { interviewId: string } | Promise<{ interviewId: string }> },
) {
  const { interviewId } = await Promise.resolve(context.params);
  const interviewIdNum = Number(interviewId);
  if (!Number.isFinite(interviewIdNum) || interviewIdNum <= 0) {
    return NextResponse.json({ detail: "invalid interview id" }, { status: 400 });
  }

  const backendBaseUrl = getBackendBaseUrl();
  const upstreamUrl = `${backendBaseUrl}/api/interviews/${interviewIdNum}/trans/export-word`;
  const upstream = await fetch(upstreamUrl, {
    method: "GET",
    headers: {
      cookie: request.headers.get("cookie") || "",
    },
    cache: "no-store",
  });

  const contentType = upstream.headers.get("content-type") || "application/octet-stream";
  const contentDisposition = upstream.headers.get("content-disposition");
  if (!upstream.ok) {
    const detailText = await upstream.text().catch(() => "");
    return new NextResponse(detailText || "export trans word failed", {
      status: upstream.status,
      headers: {
        "content-type": contentType,
      },
    });
  }

  const body = await upstream.arrayBuffer();
  const headers = new Headers();
  headers.set("content-type", contentType);
  if (contentDisposition) {
    headers.set("content-disposition", contentDisposition);
  }
  return new NextResponse(body, {
    status: upstream.status,
    headers,
  });
}
