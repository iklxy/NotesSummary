import manifest from "../data/hotword_manifest.json";

export interface HotwordOption {
  code: string;
  label: string;
  file: string;
  correction_file?: string;
}

interface HotwordManifest {
  interview: HotwordOption[];
}

const hotwordManifest = manifest as HotwordManifest;

export const HOTWORD_OPTIONS = hotwordManifest.interview ?? [];
export const INTERVIEW_HOTWORD_OPTIONS = HOTWORD_OPTIONS;
export const HOTWORD_PAGE_SIZE = 4;

export function getHotwordLabelMap(): Record<string, string> {
  const options = HOTWORD_OPTIONS;
  return options.reduce<Record<string, string>>((acc, item) => {
    acc[item.code] = item.label;
    return acc;
  }, {});
}

export function formatHotwordCodes(codes: string[] | null | undefined): string {
  if (!codes || codes.length === 0) {
    return "无";
  }
  const labelMap = getHotwordLabelMap();
  return codes.map((code) => labelMap[code] ?? code).join("，");
}

export function parseHotwordKeys(value?: string | null): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
