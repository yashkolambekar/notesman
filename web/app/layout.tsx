import type { Metadata } from "next";
import "./globals.css";
import AuthProvider from "@/components/AuthProvider";
import TopBar from "@/components/TopBar";

export const metadata: Metadata = {
  title: "Notesman",
  description: "Build exam papers from your own study material",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <TopBar />
          <main>{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
