"use client";

import React from "react";

type MarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "quote"; lines: string[] }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "empty" };

interface MarkdownContentProps {
  content?: string | null;
  className?: string;
}

function isTableSeparator(line: string): boolean {
  const trimmed = line.trim();
  return /^\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$/.test(trimmed);
}

function splitTableRow(line: string): string[] {
  const parts = line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((part) => part.trim());
  return parts;
}

function parseBlocks(content: string): MarkdownBlock[] {
  const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  const blocks: MarkdownBlock[] = [];

  let index = 0;
  while (index < lines.length) {
    while (index < lines.length && lines[index].trim().length === 0) {
      index += 1;
    }
    if (index >= lines.length) {
      break;
    }

    const line = lines[index].trimEnd();

    if (/^#{1,6}\s+/.test(line)) {
      const match = line.match(/^(#{1,6})\s+(.+)$/);
      if (match) {
        blocks.push({
          type: "heading",
          level: match[1].length,
          text: match[2].trim(),
        });
        index += 1;
        continue;
      }
    }

    if (/^>\s?/.test(line)) {
      const quoteLines: string[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        if (!/^>\s?/.test(current)) {
          break;
        }
        quoteLines.push(current.replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", lines: quoteLines });
      continue;
    }

    if (
      line.includes("|") &&
      index + 1 < lines.length &&
      isTableSeparator(lines[index + 1])
    ) {
      const header = splitTableRow(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        if (current.length === 0) {
          break;
        }
        if (!current.includes("|")) {
          break;
        }
        rows.push(splitTableRow(current));
        index += 1;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        if (!/^\s*[-*+]\s+/.test(current)) {
          break;
        }
        items.push(current.replace(/^\s*[-*+]\s+/, "").trim());
        index += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length) {
        const current = lines[index].trim();
        if (!/^\s*\d+[.)]\s+/.test(current)) {
          break;
        }
        items.push(current.replace(/^\s*\d+[.)]\s+/, "").trim());
        index += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const current = lines[index];
      const trimmed = current.trim();
      if (trimmed.length === 0) {
        index += 1;
        break;
      }
      if (
        /^#{1,6}\s+/.test(trimmed) ||
        /^>\s?/.test(trimmed) ||
        /^\s*[-*+]\s+/.test(trimmed) ||
        /^\s*\d+[.)]\s+/.test(trimmed) ||
        (trimmed.includes("|") &&
          index + 1 < lines.length &&
          isTableSeparator(lines[index + 1]))
      ) {
        break;
      }
      paragraphLines.push(trimmed);
      index += 1;
    }
    if (paragraphLines.length > 0) {
      blocks.push({ type: "paragraph", text: paragraphLines.join("\n") });
    } else {
      index += 1;
    }
  }

  return blocks.length > 0 ? blocks : [{ type: "empty" }];
}

function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(\*\*[\s\S]+?\*\*|__[\s\S]+?__)/g;
  let lastIndex = 0;

  for (const match of text.matchAll(pattern)) {
    const raw = match[0];
    const index = match.index ?? 0;
    if (index > lastIndex) {
      nodes.push(text.slice(lastIndex, index));
    }
    const inner = raw.slice(2, -2);
    nodes.push(
      <strong key={`${index}-${raw}`}>{inner}</strong>,
    );
    lastIndex = index + raw.length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

export default function MarkdownContent({ content, className }: MarkdownContentProps) {
  if (!content || content.trim().length === 0) {
    return null;
  }

  const blocks = parseBlocks(content);

  return (
    <div className={["summarynotes-markdown", className].filter(Boolean).join(" ")}>
      {blocks.map((block, blockIndex) => {
        if (block.type === "empty") {
          return null;
        }

        if (block.type === "heading") {
          const Tag = `h${Math.min(Math.max(block.level, 1), 6)}` as React.ElementType;
          return React.createElement(
            Tag,
            {
              key: `heading-${blockIndex}`,
              className: `summarynotes-markdown-h${block.level}`,
            },
            renderInline(block.text),
          );
        }

        if (block.type === "quote") {
          return (
            <blockquote key={`quote-${blockIndex}`} className="summarynotes-markdown-quote">
              {block.lines.map((line, lineIndex) => (
                <p key={`quote-${blockIndex}-${lineIndex}`}>{renderInline(line)}</p>
              ))}
            </blockquote>
          );
        }

        if (block.type === "ul" || block.type === "ol") {
          const isOrdered = block.type === "ol";
          const ListTag = block.type === "ul" ? "ul" : "div";
          return (
            <ListTag
              key={`${block.type}-${blockIndex}`}
              className={
                isOrdered
                  ? "summarynotes-markdown-list summarynotes-markdown-list-ordered"
                  : "summarynotes-markdown-list"
              }
            >
              {block.items.map((item, itemIndex) => (
                <div key={`${block.type}-${blockIndex}-${itemIndex}`} className="summarynotes-markdown-list-item">
                  <span className="summarynotes-markdown-list-bullet">·</span>
                  <span className="summarynotes-markdown-list-text">{renderInline(item)}</span>
                </div>
              ))}
            </ListTag>
          );
        }

        if (block.type === "table") {
          return (
            <div key={`table-${blockIndex}`} className="summarynotes-markdown-table-wrap">
              <table className="summarynotes-markdown-table">
                <thead>
                  <tr>
                    {block.header.map((cell, cellIndex) => (
                      <th key={`table-${blockIndex}-head-${cellIndex}`}>{renderInline(cell)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={`table-${blockIndex}-row-${rowIndex}`}>
                      {row.map((cell, cellIndex) => (
                        <td key={`table-${blockIndex}-row-${rowIndex}-cell-${cellIndex}`}>
                          {renderInline(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        return (
          <p key={`paragraph-${blockIndex}`} className="summarynotes-markdown-paragraph">
            {renderInline(block.text)}
          </p>
        );
      })}
    </div>
  );
}
