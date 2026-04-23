"use client";

import { useMemo, useState } from "react";
import { Button, Space, Typography } from "antd";
import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import type { HotwordOption } from "../lib/hotwordOptions";
import { HOTWORD_PAGE_SIZE } from "../lib/hotwordOptions";

const { Text } = Typography;

interface Props {
  title: string;
  description?: string;
  options: HotwordOption[];
  selectedKeys: string[];
  onChange: (keys: string[]) => void;
}

export default function HotwordSelector({
  title,
  description,
  options,
  selectedKeys,
  onChange,
}: Props) {
  const [page, setPage] = useState(0);

  const pageCount = Math.max(1, Math.ceil(options.length / HOTWORD_PAGE_SIZE));
  const pageOptions = useMemo(() => {
    const start = page * HOTWORD_PAGE_SIZE;
    return options.slice(start, start + HOTWORD_PAGE_SIZE);
  }, [options, page]);

  const toggle = (code: string) => {
    const next = selectedKeys.includes(code)
      ? selectedKeys.filter((item) => item !== code)
      : [...selectedKeys, code];
    onChange(next);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Text strong>{title}</Text>
        <Space size={8}>
          <Button
            size="small"
            icon={<LeftOutlined />}
            disabled={page <= 0}
            onClick={() => setPage((value) => Math.max(0, value - 1))}
          />
          <Text type="secondary">
            {page + 1} / {pageCount}
          </Text>
          <Button
            size="small"
            icon={<RightOutlined />}
            disabled={page >= pageCount - 1}
            onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}
          />
        </Space>
      </Space>
      {description ? <Text type="secondary">{description}</Text> : null}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 10,
        }}
      >
        {pageOptions.map((option) => {
          const selected = selectedKeys.includes(option.code);
          return (
            <Button
              key={option.code}
              style={{
                height: 56,
                borderRadius: 14,
                borderColor: selected ? "#1677ff" : "#d9d9d9",
                background: selected ? "#e6f4ff" : "#ffffff",
                color: "#1f2937",
                textAlign: "left",
                boxShadow: selected ? "0 8px 20px -14px rgba(22,119,255,0.55)" : undefined,
              }}
              onClick={() => toggle(option.code)}
            >
              <Space direction="vertical" size={0} style={{ width: "100%" }}>
                <Text strong>{option.label}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {selected ? "已选中" : "点击选择"}
                </Text>
              </Space>
            </Button>
          );
        })}
      </div>
      <Text type="secondary" style={{ fontSize: 12 }}>
        已选热词包：
        {selectedKeys.length > 0
          ? options
              .filter((option) => selectedKeys.includes(option.code))
              .map((option) => option.label)
              .join("，")
          : "无"}
      </Text>
    </div>
  );
}
