import type { Metadata } from "next";
import "antd/dist/reset.css";
import "./globals.css";
import { ReactQueryProvider } from "./react-query-provider";

export const metadata: Metadata = {
  title: "SummaryNotes",
  description: "访谈整理与总结工作台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased bg-slate-50">
      <body className="min-h-full flex flex-col bg-slate-50">
        <ReactQueryProvider>{children}</ReactQueryProvider>
      </body>
    </html>
  );
}
