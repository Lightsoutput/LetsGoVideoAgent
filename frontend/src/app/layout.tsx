import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@xyflow/react/dist/style.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "LetsGoVideoAgent · 视频理解工作台",
  description: "证据优先的通用视频 Multi-Agent 系统",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
