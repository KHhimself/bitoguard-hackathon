import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/lib/providers";

export const metadata: Metadata = {
  title: "BitoGuard Dashboard",
  description: "AML Risk Monitoring Platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-TW">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700&family=Noto+Sans+TC:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
