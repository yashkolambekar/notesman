"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const PLUGINS = [remarkGfm];

/** Parsing Markdown is the slowest thing on the page, so only redo it when the text itself changes. */
function Md({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={PLUGINS}>{children}</ReactMarkdown>
    </div>
  );
}

export default memo(Md);
