"use client";

import Image from "next/image";
import type { ReactNode } from "react";
import { Typography } from "antd";
import { BRAND_BADGE, BRAND_LOGO_SRC, BRAND_NAME } from "../lib/branding";

const { Title, Paragraph } = Typography;

interface BrandMarkProps {
  centered?: boolean;
  className?: string;
  size?: "sm" | "md" | "lg";
}

interface BrandHeroProps {
  title: ReactNode;
  description?: ReactNode;
  backButton?: ReactNode;
  actions?: ReactNode;
  stats?: ReactNode;
  tags?: ReactNode;
  className?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  contentMaxWidthClassName?: string;
}

const BRAND_SIZE_MAP: Record<NonNullable<BrandMarkProps["size"]>, { badgeClassName: string; logoClassName: string; titleClassName: string }> = {
  sm: {
    badgeClassName: "px-3 py-2",
    logoClassName: "h-7",
    titleClassName: "text-sm",
  },
  md: {
    badgeClassName: "px-3 py-2",
    logoClassName: "h-8",
    titleClassName: "text-[13px]",
  },
  lg: {
    badgeClassName: "px-4 py-3",
    logoClassName: "h-10",
    titleClassName: "text-base",
  },
};

export function BrandMark({ centered = false, className, size = "md" }: BrandMarkProps) {
  const sizeClass = BRAND_SIZE_MAP[size];
  return (
    <div
      className={[
        "inline-flex items-center gap-3 rounded-full border border-slate-200 bg-white shadow-[0_16px_36px_-24px_rgba(15,23,42,0.28)]",
        centered ? "mx-auto" : "",
        sizeClass.badgeClassName,
        className ?? "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Image
        src={BRAND_LOGO_SRC}
        alt="BenHealth logo"
        width={2126}
        height={1004}
        className={`${sizeClass.logoClassName} w-auto object-contain`}
        priority
      />
      <div className="flex flex-col leading-tight">
        <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-500">
          {BRAND_BADGE}
        </span>
        <span className={`${sizeClass.titleClassName} font-semibold text-slate-900`}>{BRAND_NAME}</span>
      </div>
    </div>
  );
}

export default function BrandHero({
  title,
  description,
  backButton,
  actions,
  stats,
  tags,
  className,
  titleClassName,
  descriptionClassName,
  contentMaxWidthClassName = "max-w-4xl",
}: BrandHeroProps) {
  return (
    <div
      className={[
        "relative isolate z-10 overflow-hidden border-b border-slate-200 bg-gradient-to-r from-white via-slate-50 to-cyan-50 px-6 pb-14 pt-8 shadow-[0_20px_60px_-24px_rgba(15,23,42,0.08)] md:px-10 md:pb-16 md:pt-10",
        className ?? "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-sky-400/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-12 left-1/3 h-44 w-44 rounded-full bg-cyan-300/12 blur-3xl" />
      <div className="relative flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
        <div className={contentMaxWidthClassName}>
          <BrandMark />
          {backButton ? <div className="mt-4">{backButton}</div> : null}
          <Title level={2} className={`!mb-2 !mt-4 !text-slate-900 ${titleClassName ?? ""}`.trim()}>
            {title}
          </Title>
          {description ? (
            <Paragraph className={`!mb-0 !max-w-3xl !text-slate-600 ${descriptionClassName ?? ""}`.trim()}>
              {description}
            </Paragraph>
          ) : null}
          {tags ? <div className="mt-4 flex flex-wrap gap-2">{tags}</div> : null}
        </div>
        {actions || stats ? (
          <div className="flex flex-col items-start gap-4 md:items-end">
            {stats}
            {actions}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export { BRAND_BADGE, BRAND_LOGO_SRC, BRAND_NAME };
