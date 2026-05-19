"use client";

import { toPng } from "html-to-image";

export const OVERALL_NOTES_CARD_EXPORT_ID = "summarynotes-overall-notes-cards-export";

function extractFilename(contentDisposition: string | null, fallback: string): string {
  const header = contentDisposition || "";
  const filenameStarMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
  const filenameMatch = header.match(/filename="?([^"]+)"?/i);
  if (filenameStarMatch?.[1]) {
    try {
      return decodeURIComponent(filenameStarMatch[1]);
    } catch {
      return filenameStarMatch[1];
    }
  }
  if (filenameMatch?.[1]) {
    return filenameMatch[1];
  }
  return fallback;
}

export async function captureElementAsPng(element: HTMLElement): Promise<Blob> {
  const ownerDocument = element.ownerDocument;
  await Promise.resolve(ownerDocument?.fonts?.ready);
  const dataUrl = await toPng(element, {
    cacheBust: true,
    backgroundColor: "transparent",
    pixelRatio: 2,
  });
  return await (await fetch(dataUrl)).blob();
}

async function waitForExportElement(timeoutMs = 15000): Promise<HTMLElement> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const element = document.getElementById(OVERALL_NOTES_CARD_EXPORT_ID);
    if (element instanceof HTMLElement) {
      return element;
    }
    await new Promise<void>((resolve) => window.setTimeout(() => resolve(), 100));
  }
  throw new Error("card region not found in current page");
}

export async function captureOverallNotesCardsPng(): Promise<Blob> {
  await Promise.resolve(document.fonts?.ready);
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  const element = await waitForExportElement();
  return await captureElementAsPng(element);
}

export async function exportOverallNotesWordWithImage(
  interviewId: number,
  cardImage: Blob,
): Promise<{ blob: Blob; filename: string }> {
  const formData = new FormData();
  formData.append("card_image", cardImage, `interview_${interviewId}_overall_notes_cards.png`);
  const resp = await fetch(`/api/interviews/${interviewId}/overall-notes/export-word`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (!resp.ok) {
    const detailText = await resp.text();
    let detail: unknown = detailText;
    try {
      detail = detailText ? JSON.parse(detailText) : detailText;
    } catch {
      detail = detailText;
    }
    throw new Error(`export overall notes word failed: ${JSON.stringify(detail)}`);
  }
  return {
    blob: await resp.blob(),
    filename: extractFilename(resp.headers.get("content-disposition"), `interview_${interviewId}_overall_notes.docx`),
  };
}
