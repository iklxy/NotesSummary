import type { Metadata } from "next";
import "antd/dist/reset.css";
import "./globals.css";
import { ReactQueryProvider } from "./react-query-provider";
import { BRAND_LOGO_SRC, BRAND_NAME, BRAND_TAGLINE } from "../lib/branding";

export const metadata: Metadata = {
  title: BRAND_NAME,
  description: BRAND_TAGLINE,
  icons: {
    icon: BRAND_LOGO_SRC,
  },
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
