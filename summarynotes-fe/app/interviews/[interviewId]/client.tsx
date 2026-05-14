"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useRouter } from "next/navigation";
import {
  Layout,
  Typography,
  Spin,
  Alert,
  Card,
  Button,
  Input,
  InputNumber,
  Space,
  Collapse,
  Modal,
  message,
  Tag,
  Select,
  Slider,
} from "antd";
import {
  ArrowLeftOutlined,
  AudioMutedOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  SoundOutlined,
  StepBackwardOutlined,
  StepForwardOutlined,
} from "@ant-design/icons";
import MarkdownContent from "../../../components/MarkdownContent";
import {
  createInterviewQuestions,
  deleteQuestion,
  createQuestionFewshotSample,
  deleteQuestionFewshotSample,
  generateQuestionNotes,
  getInterviewFewshotSamples,
  getInterviewAudioUrl,
  getInterviewQuestions,
  getQuestionIntents,
  getInterviewNotes,
  getInterviewSummary,
  updateInterviewSummary,
} from "../../../lib/interviewsApi";
import type {
  InterviewSummaryResponse,
  InterviewSummaryItem,
} from "../../../lib/interviewsApi";
import type {
  InterviewNotesResponse,
  InterviewFewshotSamplesResponse,
  InterviewQuestionsResponse,
  FewshotSampleItem,
  QuestionIntentItem,
  QuestionItem,
} from "../../../lib/types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  interviewId: number;
}

interface FewshotEvidenceDraft {
  uid: string;
  summary_id: string;
  speaker: string;
  text: string;
}

interface FewshotDraft {
  intent_id?: number;
  summary: string;
  analysis: string;
  confidence: number;
  evidence: FewshotEvidenceDraft[];
}

interface AudioTimestampRange {
  startMs: number;
  endMs: number;
}

/**
 * 将 summary 字段里保存的毫秒区间字符串解析成可操作的时间范围。
 * 支持 "1234-5678" 和单点 "1234" 两种写法。
 */
function parseAudioTimestampRange(timestamp?: string | null): AudioTimestampRange | null {
  if (!timestamp) {
    return null;
  }
  const match = timestamp.trim().match(/^(\d+)(?:-(\d+))?$/);
  if (!match) {
    return null;
  }
  const startMs = Number(match[1]);
  const endMs = match[2] ? Number(match[2]) : startMs;
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {
    return null;
  }
  return {
    startMs: Math.min(startMs, endMs),
    endMs: Math.max(startMs, endMs),
  };
}

/**
 * 将毫秒数格式化为 mm:ss，用于 summary 标签和播放器时间显示。
 */
function formatAudioClock(ms: number): string {
  const safeMs = Math.max(0, Math.floor(ms));
  const totalSeconds = Math.floor(safeMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * 将 summary 的原始时间戳转成用户更易读的 mm:ss 区间。
 */
function formatAudioTimestampRange(timestamp?: string | null): string {
  const range = parseAudioTimestampRange(timestamp);
  if (!range) {
    return timestamp?.trim() || "";
  }
  const start = formatAudioClock(range.startMs);
  const end = formatAudioClock(range.endMs);
  return start === end ? start : `${start} - ${end}`;
}

function createEmptyFewshotDraft(intentId?: number): FewshotDraft {
  return {
    intent_id: intentId,
    summary: "",
    analysis: "",
    confidence: 0.95,
    evidence: [
      {
        uid: `${Date.now()}-evidence-0`,
        summary_id: "",
        speaker: "",
        text: "",
      },
    ],
  };
}

/**
 * 将秒级时间换算为音频播放器常见的 mm:ss 或 h:mm:ss 显示。
 */
function formatAudioDuration(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

/**
 * 将解码后的音频缓冲区压缩成固定数量的峰值条。
 * 这里直接基于音频文件本身的采样数据计算轮廓，而不是依赖播放时的实时分析器。
 */
function buildWaveformPeaksFromAudioBuffer(
  audioBuffer: AudioBuffer,
  barCount: number,
): number[] {
  const safeBarCount = Math.max(24, barCount);
  const totalSamples = audioBuffer.length;
  const bucketSize = Math.max(1, Math.floor(totalSamples / safeBarCount));
  const channelCount = Math.max(1, audioBuffer.numberOfChannels);
  const channels = Array.from({ length: channelCount }, (_, channelIndex) =>
    audioBuffer.getChannelData(channelIndex),
  );
  const levels: number[] = [];

  for (let barIndex = 0; barIndex < safeBarCount; barIndex += 1) {
    const start = barIndex * bucketSize;
    const end = barIndex === safeBarCount - 1 ? totalSamples : Math.min(totalSamples, start + bucketSize);
    let peak = 0;
    const step = Math.max(1, Math.floor((end - start) / 180));
    for (let index = start; index < end; index += step) {
      let mixedSample = 0;
      for (let channelIndex = 0; channelIndex < channels.length; channelIndex += 1) {
        mixedSample += Math.abs(channels[channelIndex]?.[index] ?? 0);
      }
      const normalizedSample = mixedSample / channelCount;
      if (normalizedSample > peak) {
        peak = normalizedSample;
      }
    }
    const normalized = Math.min(1, Math.max(0.08, Math.pow(peak, 0.85)));
    levels.push(normalized);
  }

  return levels;
}

export default function InterviewDetailClient({ interviewId }: Props) {
  const router = useRouter();
  const interviewIdNum = interviewId;
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pendingSeekRef = useRef<{ seekMs: number; autoplay: boolean } | null>(null);
  const waveformLoadTokenRef = useRef(0);

  const [summary, setSummary] = useState<InterviewSummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const projectId = summary?.project_id ?? null;
  const [editingSummaryId, setEditingSummaryId] = useState<number | null>(null);
  const [draftSummaryText, setDraftSummaryText] = useState("");
  const [savingSummaryId, setSavingSummaryId] = useState<number | null>(null);
  const [audioDuration, setAudioDuration] = useState(0);
  const [audioCurrentTime, setAudioCurrentTime] = useState(0);
  const [audioIsPlaying, setAudioIsPlaying] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [audioSeeking, setAudioSeeking] = useState(false);
  const [audioVolume, setAudioVolume] = useState(0.85);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [waveformPeaks, setWaveformPeaks] = useState<number[]>(
    Array.from({ length: 96 }, () => 0.12),
  );

  const [notes, setNotes] = useState<InterviewNotesResponse | null>(null);
  const [notesLoading, setNotesLoading] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [notesReloadToken, setNotesReloadToken] = useState(0);
  const [questions, setQuestions] = useState<InterviewQuestionsResponse | null>(null);
  const [questionsLoading, setQuestionsLoading] = useState(false);
  const [questionsError, setQuestionsError] = useState<string | null>(null);
  const [questionsReloadToken, setQuestionsReloadToken] = useState(0);

  const [questionIntents, setQuestionIntents] = useState<QuestionIntentItem[]>([]);
  const [questionIntentsLoading, setQuestionIntentsLoading] = useState(false);
  const [savingQuestions, setSavingQuestions] = useState(false);
  const [generatingQuestionId, setGeneratingQuestionId] = useState<number | null>(null);
  const [deletingQuestionId, setDeletingQuestionId] = useState<number | null>(null);
  const [questionToDelete, setQuestionToDelete] = useState<QuestionItem | null>(null);
  const [fewshotSamples, setFewshotSamples] = useState<FewshotSampleItem[]>([]);
  const [fewshotSamplesLoading, setFewshotSamplesLoading] = useState(false);
  const [fewshotSamplesError, setFewshotSamplesError] = useState<string | null>(null);
  const [fewshotReloadToken, setFewshotReloadToken] = useState(0);
  const [fewshotModalOpen, setFewshotModalOpen] = useState(false);
  const [fewshotTargetQuestion, setFewshotTargetQuestion] = useState<QuestionItem | null>(null);
  const [savingFewshot, setSavingFewshot] = useState(false);
  const [deletingFewshotId, setDeletingFewshotId] = useState<number | null>(null);
  const [fewshotDraft, setFewshotDraft] = useState<FewshotDraft>(
    createEmptyFewshotDraft(undefined),
  );
  const [questionDrafts, setQuestionDrafts] = useState<
    Array<{
      uid: string;
      question_text: string;
    }>
  >([
    {
      uid: "draft-0",
      question_text: "",
    },
  ]);

  useEffect(() => {
    const loadSummary = async () => {
      try {
        setSummaryLoading(true);
        setSummaryError(null);
        const data = await getInterviewSummary(interviewIdNum);
        setSummary(data);
      } catch (e) {
        setSummaryError(e instanceof Error ? e.message : "加载录音原文失败");
      } finally {
        setSummaryLoading(false);
      }
    };

    if (interviewIdNum > 0) {
      void loadSummary();
    } else {
      setSummaryError("无效的访谈 ID");
    }
  }, [interviewIdNum]);

  useEffect(() => {
    setAudioDuration(0);
    setAudioCurrentTime(0);
    setAudioIsPlaying(false);
    setAudioError(null);
    setAudioSeeking(false);
    setAudioVolume(0.85);
    setPlaybackRate(1);
    setWaveformPeaks(Array.from({ length: 96 }, (_, index) => (index % 7 === 0 ? 0.72 : 0.18)));
    pendingSeekRef.current = null;
    waveformLoadTokenRef.current += 1;
  }, [interviewIdNum]);

  useEffect(() => {
    return () => {
      waveformLoadTokenRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    audio.volume = Math.min(1, Math.max(0, audioVolume));
  }, [audioVolume]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    audio.playbackRate = Math.min(2, Math.max(0.5, playbackRate));
  }, [playbackRate]);

  useEffect(() => {
    const loadNotes = async () => {
      try {
        setNotesLoading(true);
        setNotesError(null);
        const data = await getInterviewNotes(interviewIdNum);
        setNotes(data);
      } catch (e) {
        setNotesError(e instanceof Error ? e.message : "加载 QS & Notes 失败");
      } finally {
        setNotesLoading(false);
      }
    };

    if (interviewIdNum > 0) {
      void loadNotes();
    } else {
      setNotesError("无效的访谈 ID");
    }
  }, [interviewIdNum, notesReloadToken]);

  useEffect(() => {
    const loadQuestions = async () => {
      try {
        setQuestionsLoading(true);
        setQuestionsError(null);
        const data = await getInterviewQuestions(interviewIdNum);
        setQuestions(data);
      } catch (e) {
        setQuestionsError(e instanceof Error ? e.message : "加载 QS 失败");
      } finally {
        setQuestionsLoading(false);
      }
    };

    if (interviewIdNum > 0) {
      void loadQuestions();
    } else {
      setQuestionsError("无效的访谈 ID");
    }
  }, [interviewIdNum, questionsReloadToken]);

  useEffect(() => {
    const loadFewshotSamples = async () => {
      try {
        setFewshotSamplesLoading(true);
        setFewshotSamplesError(null);
        const data = await getInterviewFewshotSamples(interviewIdNum);
        setFewshotSamples(data.samples || []);
      } catch (e) {
        setFewshotSamplesError(e instanceof Error ? e.message : "加载 few-shot 种子失败");
      } finally {
        setFewshotSamplesLoading(false);
      }
    };

    if (interviewIdNum > 0) {
      void loadFewshotSamples();
    } else {
      setFewshotSamplesError("无效的访谈 ID");
    }
  }, [interviewIdNum, fewshotReloadToken]);

  useEffect(() => {
    const loadQuestionIntents = async () => {
      try {
        setQuestionIntentsLoading(true);
        const data = await getQuestionIntents();
        setQuestionIntents(data);
      } catch (e) {
        if (e instanceof Error) {
          message.error(e.message);
        } else {
          message.error("加载 few-shot intent 失败");
        }
      } finally {
        setQuestionIntentsLoading(false);
      }
    };

    void loadQuestionIntents();
  }, []);

  useEffect(() => {
    if (!fewshotModalOpen) {
      return;
    }
    if (fewshotDraft.intent_id || questionIntents.length === 0) {
      return;
    }
    const fallbackIntentId = fewshotTargetQuestion?.intent_id ?? questionIntents[0]?.id;
    if (fallbackIntentId) {
      setFewshotDraft((prev) => ({
        ...prev,
        intent_id: fallbackIntentId,
      }));
    }
  }, [fewshotModalOpen, fewshotDraft.intent_id, fewshotTargetQuestion, questionIntents]);

  const speakerSideMap = useMemo(() => {
    const map: Record<string, "left" | "right"> = {};
    if (!summary?.items) {
      return map;
    }
    let assignedCount = 0;
    for (const item of summary.items) {
      const speaker = (item.speaker || "").trim();
      if (!speaker) {
        continue;
      }
      if (map[speaker]) {
        continue;
      }
      if (assignedCount === 0) {
        map[speaker] = "left";
      } else if (assignedCount === 1) {
        map[speaker] = "right";
      } else {
        map[speaker] = "left";
      }
      assignedCount += 1;
      if (assignedCount >= 2) {
        break;
      }
    }
    return map;
  }, [summary]);

  const audioUrl = useMemo(() => getInterviewAudioUrl(interviewIdNum), [interviewIdNum]);

  useEffect(() => {
    const loadWaveformPeaks = async () => {
      if (!audioUrl || typeof window === "undefined") {
        return;
      }

      const token = waveformLoadTokenRef.current + 1;
      waveformLoadTokenRef.current = token;
      const fallbackPeaks = Array.from({ length: 96 }, (_, index) =>
        index % 7 === 0 ? 0.72 : index % 5 === 0 ? 0.42 : 0.18,
      );
      setWaveformPeaks(fallbackPeaks);

      const AudioContextCtor =
        window.AudioContext ||
        (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) {
        return;
      }

      try {
        const response = await fetch(audioUrl, { cache: "force-cache" });
        if (!response.ok) {
          throw new Error(`音频文件请求失败: ${response.status}`);
        }

        const arrayBuffer = await response.arrayBuffer();
        if (waveformLoadTokenRef.current !== token) {
          return;
        }

        const context = new AudioContextCtor();
        const decodedBuffer = await context.decodeAudioData(arrayBuffer.slice(0));
        const peaks = buildWaveformPeaksFromAudioBuffer(decodedBuffer, 96);
        if (waveformLoadTokenRef.current === token) {
          setWaveformPeaks(peaks);
        }
        await context.close();
      } catch {
        if (waveformLoadTokenRef.current === token) {
          setWaveformPeaks(fallbackPeaks);
        }
      }
    };

    void loadWaveformPeaks();
  }, [audioUrl]);

  const audioTickMarks = useMemo(() => {
    const duration = Math.max(0, audioDuration || 0);
    if (!duration) {
      return [0, 120, 240, 360, 480, 600];
    }
    const step = duration > 20 * 60 ? 120 : duration > 10 * 60 ? 60 : duration > 5 * 60 ? 30 : 15;
    const marks: number[] = [];
    for (let pos = 0; pos <= duration; pos += step) {
      marks.push(pos);
    }
    if (marks[marks.length - 1] !== duration) {
      marks.push(duration);
    }
    return marks;
  }, [audioDuration]);

  const summaryAudioRanges = useMemo(() => {
    return (summary?.items || [])
      .map((item) => ({
        item,
        range: parseAudioTimestampRange(item.timestamp),
      }))
      .filter((entry) => entry.range !== null)
      .map((entry) => ({
        id: entry.item.id,
        startMs: entry.range!.startMs,
        endMs: entry.range!.endMs,
      }));
  }, [summary]);

  const activeSummaryId = useMemo(() => {
    if (summaryAudioRanges.length === 0) {
      return null;
    }
    const currentMs = Math.floor(audioCurrentTime * 1000);
    for (let index = summaryAudioRanges.length - 1; index >= 0; index -= 1) {
      const entry = summaryAudioRanges[index];
      if (currentMs >= entry.startMs && currentMs <= entry.endMs + 200) {
        return entry.id;
      }
    }
    return null;
  }, [audioCurrentTime, summaryAudioRanges]);

  const fewshotSamplesByQuestion = useMemo(() => {
    const map: Record<number, FewshotSampleItem[]> = {};
    for (const sample of fewshotSamples) {
      const key = sample.question_id;
      if (!map[key]) {
        map[key] = [];
      }
      map[key].push(sample);
    }
    return map;
  }, [fewshotSamples]);

  const getSideLabel = (side: "left" | "right") => (side === "left" ? "1" : "2");

  const getNoteObject = (noteJson: unknown): Record<string, unknown> | null => {
    if (noteJson && typeof noteJson === "object" && !Array.isArray(noteJson)) {
      return noteJson as Record<string, unknown>;
    }
    return null;
  };

  const getEvidenceItems = (noteJson: unknown): Array<Record<string, unknown>> => {
    const noteObj = getNoteObject(noteJson);
    if (!noteObj) {
      return [];
    }
    const evidence = noteObj.evidence;
    if (!Array.isArray(evidence)) {
      return [];
    }
    return evidence.filter((item): item is Record<string, unknown> => {
      return item !== null && typeof item === "object" && !Array.isArray(item);
    });
  };

  const getEvidenceSummaryIds = (item: Record<string, unknown>): string[] => {
    const raw = item.summary_id;
    if (typeof raw === "number" || typeof raw === "string") {
      return [String(raw)];
    }
    if (Array.isArray(raw)) {
      return raw
        .filter((value) => typeof value === "number" || typeof value === "string")
        .map((value) => String(value));
    }
    return [];
  };

  const getNoteStringField = (
    noteJson: unknown,
    fieldName: "summary" | "analysis",
  ): string => {
    const noteObj = getNoteObject(noteJson);
    if (!noteObj) {
      return "";
    }
    const value = noteObj[fieldName];
    return typeof value === "string" ? value : "";
  };

  const seekAudioToMs = async (seekMs: number, autoplay: boolean) => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(seekMs) || seekMs < 0) {
      return;
    }

    const applySeek = async () => {
      const nextTime = seekMs / 1000;
      audio.currentTime = nextTime;
      setAudioCurrentTime(nextTime);
      if (autoplay) {
        await audio.play();
        setAudioIsPlaying(true);
      }
    };

    if (audio.readyState < 1) {
      pendingSeekRef.current = { seekMs, autoplay };
      audio.load();
      return;
    }

    try {
      await applySeek();
    } catch (e) {
      message.warning(e instanceof Error ? e.message : "定位音频失败");
      setAudioIsPlaying(false);
    }
  };

  const handleSummaryClick = async (item: InterviewSummaryItem) => {
    const range = parseAudioTimestampRange(item.timestamp);
    scrollToSummary(String(item.id));
    if (!range) {
      message.info("当前 summary 还没有可用时间戳");
      return;
    }
    await seekAudioToMs(range.startMs, true);
  };

  const handleAudioToggle = async () => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    if (audio.paused) {
      try {
        await audio.play();
        setAudioIsPlaying(true);
      } catch (e) {
        setAudioIsPlaying(false);
        message.warning(e instanceof Error ? e.message : "播放失败");
      }
      return;
    }
    audio.pause();
    setAudioIsPlaying(false);
  };

  const handleAudioLoadedMetadata = () => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    setAudioDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
    setAudioError(null);
    const pending = pendingSeekRef.current;
    if (pending) {
      pendingSeekRef.current = null;
      void seekAudioToMs(pending.seekMs, pending.autoplay);
    }
  };

  const handleAudioTimeUpdate = () => {
    const audio = audioRef.current;
    if (!audio || audioSeeking) {
      return;
    }
    setAudioCurrentTime(audio.currentTime);
  };

  const handleAudioSeekChange = (value: number) => {
    setAudioSeeking(true);
    setAudioCurrentTime(value);
  };

  const handleAudioSeekAfterChange = async (value: number) => {
    setAudioSeeking(false);
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    try {
      audio.currentTime = value;
      setAudioCurrentTime(value);
    } catch (e) {
      message.warning(e instanceof Error ? e.message : "拖动进度条失败");
    }
  };

  const handleAudioEnded = () => {
    setAudioIsPlaying(false);
  };

  const handleAudioError = () => {
    setAudioIsPlaying(false);
    setAudioError("音频加载失败，请确认原始文件仍可访问");
  };

  const handleAudioVolumeChange = (value: number) => {
    const nextVolume = Math.min(1, Math.max(0, value));
    setAudioVolume(nextVolume);
    const audio = audioRef.current;
    if (audio) {
      audio.volume = nextVolume;
    }
  };

  const handlePlaybackRateChange = (rate: number) => {
    const nextRate = Math.min(2, Math.max(0.5, rate));
    setPlaybackRate(nextRate);
    const audio = audioRef.current;
    if (audio) {
      audio.playbackRate = nextRate;
    }
  };

  const handleWaveformSeek = async (ratio: number) => {
    if (!audioDuration || audioDuration <= 0) {
      return;
    }
    const seekTime = Math.min(audioDuration, Math.max(0, audioDuration * ratio));
    await seekAudioToMs(seekTime * 1000, audioIsPlaying);
  };

  const handleWaveformClick = async (event: ReactMouseEvent<HTMLDivElement>) => {
    if (!audioDuration || audioDuration <= 0) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const offsetX = Math.min(rect.width, Math.max(0, event.clientX - rect.left));
    const ratio = rect.width > 0 ? offsetX / rect.width : 0;
    await handleWaveformSeek(ratio);
  };

  const handleSkipSeconds = async (deltaSeconds: number) => {
    const nextTime = Math.min(audioDuration || 0, Math.max(0, audioCurrentTime + deltaSeconds));
    await seekAudioToMs(nextTime * 1000, audioIsPlaying);
  };

  const isMuted = audioVolume <= 0.01;
  const beginEditSummary = (summaryId: number, text: string) => {
    setEditingSummaryId(summaryId);
    setDraftSummaryText(text);
  };

  const cancelEditSummary = () => {
    setEditingSummaryId(null);
    setDraftSummaryText("");
  };

  const saveSummary = async (summaryId: number) => {
    const trimmed = draftSummaryText.trim();
    if (!trimmed) {
      message.warning("summary 内容不能为空");
      return;
    }
    try {
      setSavingSummaryId(summaryId);
      const result = await updateInterviewSummary(interviewIdNum, summaryId, trimmed);
      setSummary((prev) => {
        if (!prev) {
          return prev;
        }
        return {
          ...prev,
          items: prev.items.map((item) =>
            item.id === summaryId ? { ...item, text: trimmed } : item,
          ),
        };
      });
      cancelEditSummary();
      if (result.reindex_succeeded) {
        message.success("已保存并重建索引");
      } else if (result.reindex_warning) {
        message.warning(`已保存，但索引重建存在警告：${result.reindex_warning}`);
      } else {
        message.success("已保存");
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存 summary 失败");
    } finally {
      setSavingSummaryId(null);
    }
  };

  const addQuestionDraft = () => {
    setQuestionDrafts((prev) => [
      ...prev,
      {
        uid: `${Date.now()}-${prev.length}`,
        question_text: "",
      },
    ]);
  };

  const updateQuestionDraft = (
    uid: string,
    patch: Partial<{ question_text: string }>,
  ) => {
    setQuestionDrafts((prev) =>
      prev.map((draft) => (draft.uid === uid ? { ...draft, ...patch } : draft)),
    );
  };

  const clearQuestionDraft = (uid: string) => {
    setQuestionDrafts((prev) =>
      prev.map((draft) =>
      draft.uid === uid
          ? {
              ...draft,
              question_text: "",
            }
          : draft,
      ),
    );
  };

  const saveQuestionDrafts = async () => {
    const cleaned = questionDrafts.map((draft) => ({
      question_text: draft.question_text.trim(),
    }));

    if (cleaned.length === 0) {
      message.error("请至少填写一个需总结的问题");
      return;
    }
    if (cleaned.some((item) => !item.question_text)) {
      message.error("请先补全所有需总结的问题");
      return;
    }
    try {
      setSavingQuestions(true);
      await createInterviewQuestions(interviewIdNum, cleaned);
      message.success("问题已保存");
      setQuestionDrafts([
        {
          uid: `${Date.now()}-0`,
          question_text: "",
        },
      ]);
      setQuestionsReloadToken((v) => v + 1);
      setNotesReloadToken((v) => v + 1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存问题失败");
    } finally {
      setSavingQuestions(false);
    }
  };

  const openFewshotModal = (question: QuestionItem) => {
    const fallbackIntentId = question.intent_id ?? questionIntents[0]?.id;
    setFewshotTargetQuestion(question);
    setFewshotDraft(createEmptyFewshotDraft(fallbackIntentId));
    setFewshotModalOpen(true);
  };

  const closeFewshotModal = () => {
    setFewshotModalOpen(false);
    setFewshotTargetQuestion(null);
    setFewshotDraft(createEmptyFewshotDraft(questionIntents[0]?.id));
  };

  const updateFewshotEvidence = (
    uid: string,
    patch: Partial<{ summary_id: string; speaker: string; text: string }>,
  ) => {
    setFewshotDraft((prev) => ({
      ...prev,
      evidence: prev.evidence.map((item) => (item.uid === uid ? { ...item, ...patch } : item)),
    }));
  };

  const addFewshotEvidence = () => {
    setFewshotDraft((prev) => ({
      ...prev,
      evidence: [
        ...prev.evidence,
        {
          uid: `${Date.now()}-${prev.evidence.length}`,
          summary_id: "",
          speaker: "",
          text: "",
        },
      ],
    }));
  };

  const removeFewshotEvidence = (uid: string) => {
    setFewshotDraft((prev) => {
      const nextEvidence = prev.evidence.filter((item) => item.uid !== uid);
      if (nextEvidence.length > 0) {
        return {
          ...prev,
          evidence: nextEvidence,
        };
      }
      return {
        ...prev,
        evidence: [
          {
            uid: `${Date.now()}-0`,
            summary_id: "",
            speaker: "",
            text: "",
          },
        ],
      };
    });
  };

  const saveFewshotSample = async () => {
    if (!fewshotTargetQuestion) {
      message.error("请先选择要添加种子的题目");
      return;
    }
    if (questionIntentsLoading) {
      message.info("few-shot intent 正在加载中，请稍候");
      return;
    }
    const intentId = fewshotDraft.intent_id ?? fewshotTargetQuestion.intent_id ?? questionIntents[0]?.id;
    if (!intentId) {
      message.error("请先选择 intent");
      return;
    }

    const summary = fewshotDraft.summary.trim();
    const analysis = fewshotDraft.analysis.trim();
    if (!summary) {
      message.error("summary 不能为空");
      return;
    }
    if (!analysis) {
      message.error("analysis 不能为空");
      return;
    }

    const evidence = fewshotDraft.evidence.map((item) => ({
      summary_id: Number(item.summary_id),
      speaker: item.speaker.trim() || undefined,
      text: item.text.trim(),
    }));

    if (evidence.length === 0) {
      message.error("请至少添加一条 evidence");
      return;
    }
    const rawEvidence = fewshotDraft.evidence;
    if (
      rawEvidence.some(
        (item) => item.summary_id.trim().length === 0 || item.text.trim().length === 0,
      )
    ) {
      message.error("请补全所有 evidence 的 summary_id 和内容");
      return;
    }
    if (evidence.some((item) => !Number.isFinite(item.summary_id) || item.text.length === 0)) {
      message.error("请补全所有 evidence 的 summary_id 和内容");
      return;
    }

    try {
      setSavingFewshot(true);
      await createQuestionFewshotSample(interviewIdNum, fewshotTargetQuestion.id, {
        intent_id: intentId,
        summary,
        analysis,
        evidence,
        confidence: fewshotDraft.confidence,
      });
      message.success("冷启动种子已保存");
      setFewshotReloadToken((value) => value + 1);
      closeFewshotModal();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存 few-shot 种子失败");
    } finally {
      setSavingFewshot(false);
    }
  };

  const handleDeleteFewshotSample = (sample: FewshotSampleItem) => {
    Modal.confirm({
      title: "删除冷启动种子",
      content: (
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text type="danger">删除后不可恢复</Text>
          <Text>{sample.sample_summary || "未填写 summary"}</Text>
          <Space size={8} wrap>
            <Tag color="purple">intent_id: {sample.intent_id}</Tag>
            <Tag>质量 {sample.quality_score ?? 95}</Tag>
            <Tag>证据 {sample.evidence_count ?? 0}</Tag>
          </Space>
        </Space>
      ),
      okText: "确认删除",
      cancelText: "取消",
      centered: true,
      onOk: async () => {
        try {
          setDeletingFewshotId(sample.id);
          const result = await deleteQuestionFewshotSample(interviewIdNum, sample.id);
          if (result.success) {
            message.success("冷启动种子已删除");
            setFewshotReloadToken((value) => value + 1);
          } else {
            message.error(result.message || "删除 few-shot 种子失败");
          }
        } catch (e) {
          message.error(e instanceof Error ? e.message : "删除 few-shot 种子失败");
        } finally {
          setDeletingFewshotId(null);
        }
      },
    });
  };

  const handleGenerateQuestionNotes = async (questionId: number) => {
    try {
      setGeneratingQuestionId(questionId);
      const result = await generateQuestionNotes(interviewIdNum, questionId);
      if (result.success) {
        if (result.warnings && result.warnings.length > 0) {
          message.warning(`Notes 已生成，但存在警告：${result.warnings.join("；")}`);
        } else {
          message.success("Notes 已生成");
        }
        setNotesReloadToken((v) => v + 1);
      } else {
        message.error(result.message || "生成 Notes 失败");
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "生成 Notes 失败");
    } finally {
      setGeneratingQuestionId(null);
    }
  };

  const handleDeleteQuestion = async (questionId: number, questionText: string) => {
    try {
      if (deletingQuestionId === questionId) {
        return;
      }
      const target = questions?.questions.find((item) => item.id === questionId);
      setQuestionToDelete(
        target ?? {
          id: questionId,
          project_interview_id: interviewIdNum,
          question_order: 0,
          question_text: questionText,
        },
      );
    } catch (e) {
      message.error(e instanceof Error ? e.message : "删除 QS 失败");
    }
  };

  const confirmDeleteQuestion = async () => {
    if (!questionToDelete) {
      return;
    }
    try {
      setDeletingQuestionId(questionToDelete.id);
      const result = await deleteQuestion(interviewIdNum, questionToDelete.id);
      if (result.success) {
        message.success(
          result.notes_deleted && result.notes_deleted > 0
            ? `已删除 QS，并级联删除 ${result.notes_deleted} 条 Notes`
            : "已删除 QS",
        );
        setQuestionsReloadToken((v) => v + 1);
        setNotesReloadToken((v) => v + 1);
        setQuestionToDelete(null);
      } else {
        message.error(result.message || "删除 QS 失败");
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "删除 QS 失败");
    } finally {
      setDeletingQuestionId(null);
    }
  };

  const scrollToSummary = (summaryId: string) => {
    const element = document.getElementById(`summary-item-${summaryId}`);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "center" });
      element.animate(
        [
          { boxShadow: "0 0 0 0 rgba(59, 130, 246, 0.0)" },
          { boxShadow: "0 0 0 4px rgba(59, 130, 246, 0.35)" },
          { boxShadow: "0 0 0 0 rgba(59, 130, 246, 0.0)" },
        ],
        {
          duration: 900,
          easing: "ease-out",
        },
      );
    }
  };

  return (
    <Layout className="min-h-screen">
      <Header className="flex items-center justify-between bg-slate-900 shadow px-6">
        <Space>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => {
              if (projectId && projectId > 0) {
                router.push(`/projects/${projectId}`);
              }
            }}
            disabled={!projectId || projectId <= 0}
          >
            返回项目详情
          </Button>
          <Title level={3} className="mb-0" style={{ color: "#ffffff" }}>
            访谈详情 #{interviewIdNum > 0 ? interviewIdNum : "无效"}
          </Title>
        </Space>
        <Space>
          <Button onClick={() => router.push(`/interviews/${interviewIdNum}/overall-notes`)}>
            整体 Notes
          </Button>
          <Button onClick={() => router.push(`/interviews/${interviewIdNum}/trans`)}>
            全文 trans
          </Button>
        </Space>
      </Header>
      <Content className="bg-slate-50">
        <div
          style={{
            maxWidth: 1680,
            margin: "0 auto",
            padding: "24px 24px 40px",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1.22fr) minmax(360px, 0.78fr)",
              gap: 24,
              alignItems: "start",
            }}
          >
            <Card
              style={{
                borderRadius: 24,
                boxShadow: "0 16px 48px -30px rgba(15,23,42,0.28)",
                height: "calc(100vh - 96px)",
              }}
              bodyStyle={{
                height: "100%",
                padding: 20,
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
              }}
            >
              <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
                <div>
                  <Title level={4} style={{ marginBottom: 4 }}>
                    录音原文
                  </Title>
                  <Text type="secondary">
                    按说话人气泡展示，可直接编辑修正转录。
                  </Text>
                </div>
              </Space>
              {summaryLoading ? (
                <Spin />
              ) : summaryError ? (
                <Alert type="error" message={summaryError} />
              ) : (
                <div
                  style={{
                    flex: 1,
                    minHeight: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: 16,
                  }}
                >
                  {summary?.items && summary.items.length > 0 ? (
                    <>
                      <div
                        style={{
                          flex: 1,
                          minHeight: 0,
                          overflowY: "auto",
                          paddingRight: 8,
                        }}
                      >
                        {summary.items.map((item) => {
                          const speaker = (item.speaker || "").trim() || "未知角色";
                          const side = speakerSideMap[speaker] || "left";
                          const timestamp = item.timestamp || "";
                          const text = item.text || "";
                          const isEditing = editingSummaryId === item.id;
                          const cardText = isEditing ? draftSummaryText : text;
                          const sideLabel = getSideLabel(side);
                          const isActive = activeSummaryId === item.id;
                          return (
                            <div
                              key={item.id}
                              id={`summary-item-${item.id}`}
                              style={{
                                display: "flex",
                                justifyContent: side === "left" ? "flex-start" : "flex-end",
                                marginBottom: 12,
                                cursor: isEditing ? "default" : "pointer",
                              }}
                              onClick={
                                isEditing
                                  ? undefined
                                  : () => {
                                      void handleSummaryClick(item);
                                    }
                              }
                            >
                              <Card
                                size="small"
                                style={{
                                  maxWidth: "82%",
                                  backgroundColor: isActive
                                    ? "#eff6ff"
                                    : side === "left"
                                      ? "#ffffff"
                                      : "#eef6ff",
                                  borderRadius: 18,
                                  boxShadow: isActive
                                    ? "0 12px 32px -18px rgba(37,99,235,0.55)"
                                    : "0 8px 24px -18px rgba(15,23,42,0.28)",
                                  border: isActive ? "1px solid rgba(37,99,235,0.35)" : undefined,
                                }}
                              >
                                <Space
                                  style={{ width: "100%", justifyContent: "space-between" }}
                                  align="start"
                                >
                                  <Space size={8} wrap>
                                    <Tag color={side === "left" ? "blue" : "cyan"}>
                                      {sideLabel}
                                    </Tag>
                                    {timestamp ? (
                                      <Text type="secondary" style={{ fontSize: 12 }}>
                                        {formatAudioTimestampRange(timestamp)}
                                      </Text>
                                    ) : null}
                                  </Space>
                                  {!isEditing ? (
                                    <Button
                                      type="link"
                                      size="small"
                                      style={{ padding: 0, height: "auto" }}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        beginEditSummary(item.id, text);
                                      }}
                                    >
                                      编辑
                                    </Button>
                                  ) : null}
                                </Space>
                                {!isEditing ? (
                                  <Paragraph style={{ marginBottom: 0, marginTop: 8 }}>
                                    {text}
                                  </Paragraph>
                                ) : (
                                  <div style={{ marginTop: 8 }}>
                                    <Input.TextArea
                                      value={cardText}
                                      autoSize={{ minRows: 3, maxRows: 8 }}
                                      onChange={(e) => setDraftSummaryText(e.target.value)}
                                    />
                                    <Space style={{ marginTop: 8 }}>
                                      <Button
                                        type="primary"
                                        loading={savingSummaryId === item.id}
                                        onClick={() => void saveSummary(item.id)}
                                      >
                                        保存
                                      </Button>
                                      <Button onClick={cancelEditSummary}>取消</Button>
                                    </Space>
                                  </div>
                                )}
                              </Card>
                            </div>
                          );
                        })}
                      </div>

                      <div
                        style={{
                          borderTop: "1px solid #e2e8f0",
                          paddingTop: 16,
                          background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
                          borderRadius: 18,
                        }}
                      >
                        <audio
                          ref={audioRef}
                          src={audioUrl}
                          preload="metadata"
                          onLoadedMetadata={handleAudioLoadedMetadata}
                          onTimeUpdate={handleAudioTimeUpdate}
                          onEnded={handleAudioEnded}
                          onError={handleAudioError}
                          onPlay={() => setAudioIsPlaying(true)}
                          onPause={() => setAudioIsPlaying(false)}
                          style={{ display: "none" }}
                        />
                        {audioError ? <Alert type="warning" message={audioError} /> : null}

                        <div
                          style={{
                            borderRadius: 16,
                            background: "linear-gradient(180deg, #f7fbff 0%, #edf4fb 100%)",
                            border: "1px solid #dbe7f3",
                            padding: "8px 10px 8px",
                            marginTop: 8,
                            boxShadow: "0 12px 30px -24px rgba(15, 23, 42, 0.32)",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                              marginBottom: 8,
                              flexWrap: "wrap",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                                minWidth: 132,
                              }}
                            >
                                {isMuted ? (
                                  <AudioMutedOutlined style={{ fontSize: 16, color: "#475569" }} />
                                ) : (
                                <SoundOutlined style={{ fontSize: 16, color: "#475569" }} />
                              )}
                              <div style={{ width: 92 }}>
                                <Slider
                                  min={0}
                                  max={1}
                                  step={0.01}
                                  value={audioVolume}
                                  tooltip={{
                                    formatter: (value) => `${Math.round(Number(value ?? 0) * 100)}%`,
                                  }}
                                  onChange={(value) => handleAudioVolumeChange(Number(value))}
                                  />
                                </div>
                              </div>

                              <div
                                style={{
                                  flex: 1,
                                  display: "flex",
                                  justifyContent: "center",
                                  alignItems: "center",
                                }}
                              >
                                <Space align="center" size={8}>
                                  <Button
                                    type="text"
                                    icon={<StepBackwardOutlined />}
                                    onClick={() => void handleSkipSeconds(-10)}
                                  />
                                  <Button
                                    type="primary"
                                    shape="circle"
                                    size="large"
                                    icon={
                                      audioIsPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />
                                    }
                                    onClick={() => void handleAudioToggle()}
                                  />
                                  <Button
                                    type="text"
                                    icon={<StepForwardOutlined />}
                                    onClick={() => void handleSkipSeconds(10)}
                                  />
                                </Space>
                              </div>

                              <div
                                style={{
                                  minWidth: 156,
                                  display: "flex",
                                  flexDirection: "column",
                                  alignItems: "flex-end",
                                  gap: 4,
                                }}
                              >
                                <Space size={6} wrap style={{ justifyContent: "flex-end" }}>
                                  {[1, 1.5, 2].map((rate) => (
                                    <Button
                                      key={rate}
                                      size="small"
                                      type={playbackRate === rate ? "primary" : "default"}
                                      onClick={() => handlePlaybackRateChange(rate)}
                                    >
                                      {rate.toFixed(1)}x
                                    </Button>
                                  ))}
                                </Space>
                                <Text type="secondary" style={{ fontSize: 11 }}>
                                  {formatAudioDuration(audioCurrentTime)} / {formatAudioDuration(audioDuration)}
                                </Text>
                              </div>
                          </div>

                          <div
                            onClick={(event) => void handleWaveformClick(event)}
                            style={{
                              position: "relative",
                              height: 50,
                              borderRadius: 12,
                              background: "linear-gradient(180deg, rgba(255,255,255,0.82) 0%, rgba(255,255,255,0.58) 100%)",
                              border: "1px solid rgba(148, 163, 184, 0.22)",
                              overflow: "hidden",
                              cursor: "pointer",
                              padding: "7px 10px 6px",
                            }}
                          >
                            <div
                              style={{
                                position: "absolute",
                                left: 0,
                                top: 0,
                                bottom: 0,
                                width: `${audioDuration > 0 ? (audioCurrentTime / audioDuration) * 100 : 0}%`,
                                background: "rgba(96, 165, 250, 0.18)",
                                pointerEvents: "none",
                              }}
                            />
                            <div
                              style={{
                                display: "flex",
                                alignItems: "flex-end",
                                gap: 2,
                                height: "100%",
                                position: "relative",
                                zIndex: 1,
                              }}
                            >
                              {waveformPeaks.map((level, index) => {
                                const activeRatio = audioDuration > 0 ? audioCurrentTime / audioDuration : 0;
                                const barRatio = waveformPeaks.length > 1 ? index / (waveformPeaks.length - 1) : 0;
                                const isActive = barRatio <= activeRatio;
                                const baseHeight = 0.16 + level * 0.74;
                                const height = isActive ? Math.min(1, baseHeight + 0.08) : baseHeight;
                                return (
                                  <div
                                    key={`${audioUrl}-${index}`}
                                    style={{
                                      flex: 1,
                                      minWidth: 2,
                                      maxWidth: 7,
                                      display: "flex",
                                      alignItems: "flex-end",
                                      justifyContent: "center",
                                      height: "100%",
                                    }}
                                  >
                                    <div
                                      style={{
                                        width: "100%",
                                        borderRadius: 999,
                                        height: `${Math.round(height * 100)}%`,
                                        minHeight: 6,
                                        background: isActive ? "#60a5fa" : "#cbd5e1",
                                        boxShadow: isActive
                                          ? "0 0 0 1px rgba(59, 130, 246, 0.12)"
                                          : "none",
                                        transition: "height 0.15s ease, background 0.15s ease",
                                      }}
                                    />
                                  </div>
                                );
                              })}
                            </div>
                          </div>

                          <div style={{ marginTop: 6 }}>
                            <div
                              style={{
                                position: "relative",
                                height: 18,
                                fontSize: 10,
                                color: "#64748b",
                              }}
                            >
                              {audioTickMarks.map((tick) => {
                                const left = audioDuration > 0 ? Math.min(100, (tick / audioDuration) * 100) : 0;
                                return (
                                  <div
                                    key={tick}
                                    style={{
                                      position: "absolute",
                                      left: `${left}%`,
                                      top: 0,
                                      transform: "translateX(-50%)",
                                      whiteSpace: "nowrap",
                                      textAlign: "center",
                                    }}
                                  >
                                    <div
                                    style={{
                                      width: 1,
                                      height: 8,
                                      margin: "0 auto 2px",
                                      background: "#1f2937",
                                    }}
                                    />
                                    <span>{formatAudioDuration(tick)}</span>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        </div>

                      </div>
                    </>
                  ) : (
                    <Text type="secondary">暂无原文数据。</Text>
                  )}
                </div>
              )}
            </Card>

            <div style={{ position: "sticky", top: 24, alignSelf: "start" }}>
              <Card
                style={{
                  borderRadius: 24,
                  boxShadow: "0 16px 48px -30px rgba(15,23,42,0.32)",
                  height: "calc(100vh - 96px)",
                }}
                bodyStyle={{
                  height: "100%",
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    padding: 20,
                    borderBottom: "1px solid #e2e8f0",
                    background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
                  }}
                >
                  <Title level={4} style={{ marginBottom: 4 }}>
                    QS &amp; Notes
                  </Title>
                </div>

                <div
                  style={{
                    flex: 1,
                    overflowY: "auto",
                    padding: 20,
                    display: "flex",
                    flexDirection: "column",
                    gap: 16,
                  }}
                >
                  <Card size="small" style={{ background: "#f8fafc", borderRadius: 18 }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Text strong>需总结的问题</Text>
                      <Space>
                        <Button type="dashed" onClick={addQuestionDraft}>
                          添加问题
                        </Button>
                        <Button
                          type="primary"
                          loading={savingQuestions}
                          onClick={() => void saveQuestionDrafts()}
                        >
                          保存问题
                        </Button>
                      </Space>
                    </Space>
                    <Space
                      direction="vertical"
                      style={{ width: "100%", marginTop: 12 }}
                      size="middle"
                    >
                      {questionDrafts.map((draft, index) => (
                        <Card key={draft.uid} size="small" style={{ background: "#fff" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                            <Input.TextArea
                              rows={2}
                              value={draft.question_text}
                              placeholder="请输入需总结的问题"
                              onChange={(e) =>
                                updateQuestionDraft(draft.uid, { question_text: e.target.value })
                              }
                            />
                            <div style={{ display: "flex", justifyContent: "flex-end" }}>
                              <Button danger onClick={() => clearQuestionDraft(draft.uid)}>
                                清空
                              </Button>
                            </div>
                          </div>
                        </Card>
                      ))}
                    </Space>
                  </Card>

                  <Card size="small" style={{ background: "#f8fafc", borderRadius: 18 }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Text strong>已保存的问题</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        保存后会在这里展示
                      </Text>
                    </Space>
                    <div style={{ marginTop: 12 }}>
                      {questionsLoading ? (
                        <Spin />
                      ) : questionsError ? (
                        <Alert type="error" message={questionsError} />
                      ) : questions?.questions && questions.questions.length > 0 ? (
                        <Space direction="vertical" style={{ width: "100%" }} size="middle">
                          {questions.questions.map((question: QuestionItem) => (
                            <Card key={question.id} size="small" styles={{ body: { padding: 12 } }}>
                              {(() => {
                                const questionFewshots = fewshotSamplesByQuestion[question.id] || [];
                                return (
                              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                              <Space size={8} wrap>
                                  <Tag color="geekblue">#{question.question_order}</Tag>
                                </Space>
                                <Text>{question.question_text}</Text>
                                <Space size={8} wrap>
                                  <Button
                                    size="small"
                                    loading={generatingQuestionId === question.id}
                                    onClick={() => void handleGenerateQuestionNotes(question.id)}
                                    style={{
                                      borderRadius: 999,
                                      borderColor: "#94a3b8",
                                      color: "#334155",
                                      background: "#fff",
                                    }}
                                  >
                                    生成 Notes
                                  </Button>
                                  <Button
                                    danger
                                    size="small"
                                    onClick={() =>
                                      void handleDeleteQuestion(question.id, question.question_text)
                                    }
                                    style={{
                                      borderRadius: 999,
                                      borderColor: "#fecaca",
                                      background: "#fff",
                                    }}
                                  >
                                    删除 QS
                                  </Button>
                                </Space>
                                <div
                                  style={{
                                    marginTop: 8,
                                    paddingTop: 8,
                                    borderTop: "1px dashed #e2e8f0",
                                  }}
                                >
                                <Space
                                  style={{ width: "100%", justifyContent: "space-between" }}
                                  align="center"
                                >
                                    <Space direction="vertical" size={0}>
                                      <Text type="secondary" style={{ fontSize: 12 }}>
                                        冷启动种子 ({questionFewshots.length})
                                      </Text>
                                      <Text type="secondary" style={{ fontSize: 12 }}>
                                        种子是帮助系统学习优秀回答而使用的，可不填
                                      </Text>
                                    </Space>
                                    <Button
                                      size="small"
                                      type="dashed"
                                      onClick={() => openFewshotModal(question)}
                                      disabled={questionIntentsLoading}
                                    >
                                      添加种子
                                    </Button>
                                  </Space>
                                  {fewshotSamplesLoading ? (
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      种子加载中...
                                    </Text>
                                  ) : fewshotSamplesError ? (
                                    <Text type="danger" style={{ fontSize: 12 }}>
                                      {fewshotSamplesError}
                                    </Text>
                                  ) : questionFewshots.length > 0 ? (
                                    <Space
                                      direction="vertical"
                                      style={{ width: "100%", marginTop: 8 }}
                                      size="small"
                                    >
                                      {questionFewshots.map((sample) => (
                                        <Card
                                          key={sample.id}
                                          size="small"
                                          styles={{ body: { padding: 10 } }}
                                          style={{ background: "#fafafa" }}
                                        >
                                          <Space
                                            style={{ width: "100%", justifyContent: "space-between" }}
                                            align="start"
                                          >
                                            <Space size={6} wrap>
                                              <Tag color="purple">seed</Tag>
                                              <Tag>intent_id: {sample.intent_id}</Tag>
                                              <Tag>质量 {sample.quality_score ?? 95}</Tag>
                                              <Tag>证据 {sample.evidence_count ?? 0}</Tag>
                                            </Space>
                                            <Button
                                              size="small"
                                              danger
                                              loading={deletingFewshotId === sample.id}
                                              onClick={() => handleDeleteFewshotSample(sample)}
                                            >
                                              删除
                                            </Button>
                                          </Space>
                                          {sample.sample_summary ? (
                                            <Paragraph
                                              style={{ marginTop: 8, marginBottom: 4 }}
                                              ellipsis={{ rows: 2, expandable: true, symbol: "展开" }}
                                            >
                                              {sample.sample_summary}
                                            </Paragraph>
                                          ) : null}
                                          {sample.sample_analysis ? (
                                            <Paragraph
                                              style={{ marginBottom: 4, color: "#475569" }}
                                              ellipsis={{ rows: 2, expandable: true, symbol: "展开" }}
                                            >
                                              {sample.sample_analysis}
                                            </Paragraph>
                                          ) : null}
                                          <Text type="secondary" style={{ fontSize: 12 }}>
                                            {sample.created_time || "未知时间"}
                                          </Text>
                                        </Card>
                                      ))}
                                    </Space>
                                  ) : (
                                    <Text type="secondary" style={{ fontSize: 12 }}>
                                      当前问题还没有冷启动种子。
                                    </Text>
                                  )}
                                </div>
                              </Space>
                                );
                              })()}
                            </Card>
                          ))}
                        </Space>
                      ) : (
                        <Text type="secondary">当前暂无已保存的问题。</Text>
                      )}
                    </div>
                  </Card>

                  <Card size="small" style={{ background: "#f8fafc", borderRadius: 18, flex: 1 }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Text strong>Notes</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        点击证据可定位到左侧原文
                      </Text>
                    </Space>
                    <div style={{ marginTop: 12 }}>
                      {notesLoading ? (
                        <Spin />
                      ) : notesError ? (
                        <Alert type="error" message={notesError} />
                      ) : notes?.questions && notes.questions.length > 0 ? (
                        <Space direction="vertical" style={{ width: "100%" }} size="middle">
                          {notes.questions.map((q, index) => {
                            const primaryNote = q.notes?.[0];
                            if (!primaryNote) {
                              return null;
                            }
                            const noteJson = primaryNote?.note_json;
                            const summaryText = getNoteStringField(noteJson, "summary");
                            return (
                              <Card
                                key={q.question_id}
                                style={{ marginBottom: 12 }}
                              >
                                <Title level={5}>
                                  {index + 1}. {q.question_text}
                                </Title>
                                {summaryText && (
                                  <MarkdownContent content={summaryText} />
                                )}
                                {!summaryText && (
                                  <Text type="secondary">该题暂无可展示内容。</Text>
                                )}
                              </Card>
                            );
                          })}
                        </Space>
                      ) : (
                        <Text type="secondary">暂无 QS &amp; Notes 数据。</Text>
                      )}
                    </div>
                  </Card>
                </div>
              </Card>
            </div>
          </div>
        </div>
      </Content>
      <Modal
        open={fewshotModalOpen}
        title={
          fewshotTargetQuestion
            ? `添加冷启动种子 - 第 ${fewshotTargetQuestion.question_order} 条问题`
            : "添加冷启动种子"
        }
        onCancel={closeFewshotModal}
        onOk={() => void saveFewshotSample()}
        okText="保存种子"
        cancelText="取消"
        confirmLoading={savingFewshot}
        width={920}
        destroyOnHidden
      >
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Card size="small" style={{ background: "#f8fafc" }}>
            <Space direction="vertical" size={4} style={{ width: "100%" }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                当前问题
              </Text>
              <Text>{fewshotTargetQuestion?.question_text}</Text>
              <Space size={8} wrap>
                <Tag color="geekblue">
                  #{fewshotTargetQuestion?.question_order ?? "-"}
                </Tag>
              </Space>
            </Space>
          </Card>

          <Space style={{ width: "100%" }} size="middle" align="start">
            <Select
              style={{ width: 240 }}
              value={fewshotDraft.intent_id}
              placeholder="请选择 intent"
              loading={questionIntentsLoading}
              onChange={(value) =>
                setFewshotDraft((prev) => ({
                  ...prev,
                  intent_id: value,
                }))
              }
              options={questionIntents.map((intent) => ({
                label: `${intent.id} - ${intent.name || intent.code}`,
                value: intent.id,
              }))}
              showSearch
              optionFilterProp="label"
            />
            <InputNumber
              min={0}
              max={1}
              step={0.01}
              style={{ width: 160 }}
              value={fewshotDraft.confidence}
              onChange={(value) =>
                setFewshotDraft((prev) => ({
                  ...prev,
                  confidence: typeof value === "number" ? value : 0.95,
                }))
              }
              addonBefore="confidence"
            />
          </Space>

          <div>
            <Text strong>Summary</Text>
            <Input.TextArea
              value={fewshotDraft.summary}
              autoSize={{ minRows: 3, maxRows: 6 }}
              placeholder="请输入这一条 few-shot 的 summary"
              style={{ marginTop: 8 }}
              onChange={(e) =>
                setFewshotDraft((prev) => ({ ...prev, summary: e.target.value }))
              }
            />
          </div>

          <div>
            <Text strong>Analysis</Text>
            <Input.TextArea
              value={fewshotDraft.analysis}
              autoSize={{ minRows: 4, maxRows: 8 }}
              placeholder="请输入这一条 few-shot 的 analysis"
              style={{ marginTop: 8 }}
              onChange={(e) =>
                setFewshotDraft((prev) => ({ ...prev, analysis: e.target.value }))
              }
            />
          </div>

          <Card size="small" style={{ background: "#f8fafc" }}>
            <Space style={{ width: "100%", justifyContent: "space-between" }}>
              <Text strong>Evidence</Text>
              <Button type="dashed" onClick={addFewshotEvidence}>
                添加 Evidence
              </Button>
            </Space>
            <Space direction="vertical" style={{ width: "100%", marginTop: 12 }} size="middle">
              {fewshotDraft.evidence.map((item, index) => (
                <Card key={item.uid} size="small" style={{ background: "#fff" }}>
                  <Space direction="vertical" size={10} style={{ width: "100%" }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Text type="secondary">证据 {index + 1}</Text>
                      <Button
                        size="small"
                        danger
                        onClick={() => removeFewshotEvidence(item.uid)}
                        disabled={fewshotDraft.evidence.length === 1}
                      >
                        删除
                      </Button>
                    </Space>
                    <Space style={{ width: "100%" }} size="middle">
                      <InputNumber
                        min={0}
                        style={{ width: 180 }}
                        value={item.summary_id ? Number(item.summary_id) : undefined}
                        placeholder="summary_id"
                        onChange={(value) =>
                          updateFewshotEvidence(item.uid, {
                            summary_id:
                              typeof value === "number" && Number.isFinite(value)
                                ? String(value)
                                : "",
                          })
                        }
                      />
                      <Input
                        style={{ flex: 1 }}
                        value={item.speaker}
                        placeholder="speaker（可选）"
                        onChange={(e) =>
                          updateFewshotEvidence(item.uid, { speaker: e.target.value })
                        }
                      />
                    </Space>
                    <Input.TextArea
                      value={item.text}
                      autoSize={{ minRows: 2, maxRows: 4 }}
                      placeholder="证据原文"
                      onChange={(e) =>
                        updateFewshotEvidence(item.uid, { text: e.target.value })
                      }
                    />
                  </Space>
                </Card>
              ))}
            </Space>
          </Card>
        </Space>
      </Modal>
      <Modal
        open={Boolean(questionToDelete)}
        title="删除 QS"
        onCancel={() => setQuestionToDelete(null)}
        onOk={() => void confirmDeleteQuestion()}
        okText="确认删除"
        cancelText="取消"
        confirmLoading={deletingQuestionId === questionToDelete?.id}
        destroyOnHidden
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            message="删除后不可恢复"
            description="这条 QS 以及它对应的 Notes 会从数据库中一起删除。"
          />
          <Card size="small" style={{ background: "#f8fafc" }}>
            <Space direction="vertical" size={4} style={{ width: "100%" }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                当前问题
              </Text>
              <Text>{questionToDelete?.question_text}</Text>
              <Space size={8} wrap>
                <Tag color="geekblue">#{questionToDelete?.question_order ?? "-"}</Tag>
              </Space>
            </Space>
          </Card>
        </Space>
      </Modal>
    </Layout>
  );
}
