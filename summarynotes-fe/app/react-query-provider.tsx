"use client";

import { ReactNode, useState } from "react";
import { ConfigProvider, theme as antdTheme } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

interface Props {
  children: ReactNode;
}

export function ReactQueryProvider({ children }: Props) {
  const [client] = useState(() => new QueryClient());
  return (
    <ConfigProvider
      theme={{
        algorithm: antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: "#0f766e",
          colorInfo: "#0284c7",
          colorSuccess: "#15803d",
          colorWarning: "#d97706",
          colorError: "#dc2626",
          colorBgBase: "#f5f7fb",
          colorBgContainer: "#ffffff",
          colorTextBase: "#0f172a",
          colorBorder: "#d7e1ec",
          borderRadius: 12,
          borderRadiusLG: 20,
        },
      }}
    >
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ConfigProvider>
  );
}
