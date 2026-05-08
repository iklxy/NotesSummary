import { NextRequest, NextResponse } from "next/server";

function getBackendBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (value) {
    return value.replace(/\/$/, "");
  }
  return "http://127.0.0.1:9000";
}

export async function POST(
  request: NextRequest,
  context: { params: { projectId: string } | Promise<{ projectId: string }> },
) {
  const { projectId } = await Promise.resolve(context.params);
  const projectIdNum = Number(projectId);
  if (!Number.isFinite(projectIdNum) || projectIdNum <= 0) {
    return NextResponse.json({ detail: "invalid project id" }, { status: 400 });
  }

  const body = await request.text();
  const backendBaseUrl = getBackendBaseUrl();
  const upstreamUrl = `${backendBaseUrl}/api/projects/${projectIdNum}/ca-table/export-xlsx`;
  const upstream = await fetch(upstreamUrl, {
    method: "POST",
    headers: {
      cookie: request.headers.get("cookie") || "",
      "content-type": request.headers.get("content-type") || "application/json",
    },
    body,
    cache: "no-store",
  });

  const contentType = upstream.headers.get("content-type") || "application/octet-stream";
  const contentDisposition = upstream.headers.get("content-disposition");
  if (!upstream.ok) {
    const detailText = await upstream.text().catch(() => "");
    return new NextResponse(detailText || "export ca xlsx failed", {
      status: upstream.status,
      headers: {
        "content-type": contentType,
      },
    });
  }

  const responseBody = await upstream.arrayBuffer();
  const headers = new Headers();
  headers.set("content-type", contentType);
  if (contentDisposition) {
    headers.set("content-disposition", contentDisposition);
  }
  return new NextResponse(responseBody, {
    status: upstream.status,
    headers,
  });
}
