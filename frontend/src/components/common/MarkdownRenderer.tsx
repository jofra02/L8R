import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { cn } from "@/lib/utils";

type MarkdownVariant = "full" | "compact" | "inline";

interface MarkdownRendererProps {
  content: string;
  /**
   * full    — agent reports (Report tab, Final Answer): full typography.
   * compact — user-submitted text (ticket description): same typography,
   *           plus single-newline line breaks (remark-breaks).
   * inline  — short prose fields (hypotheses, plan steps, evidence summaries):
   *           no block margins, inherits the surrounding text color/size.
   */
  variant?: MarkdownVariant;
  className?: string;
}

const PROSE_CLASSES = [
  "prose prose-invert prose-sm max-w-none",
  "prose-headings:text-text-primary",
  "prose-p:text-text-secondary prose-li:text-text-secondary",
  "prose-strong:text-text-primary prose-a:text-accent",
  "prose-code:bg-elevated prose-code:text-text-primary prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:font-normal prose-code:before:content-none prose-code:after:content-none",
  "prose-pre:bg-elevated prose-pre:border prose-pre:border-border",
  "prose-blockquote:text-text-secondary prose-blockquote:border-border",
  "prose-hr:border-border",
  "prose-th:text-text-primary prose-th:border-border prose-td:border-border prose-tr:border-border",
].join(" ");

const INLINE_CLASSES = [
  "[&_p]:my-0 [&_p:not(:last-child)]:mb-1",
  "[&_ul]:my-1 [&_ul]:pl-4 [&_ul]:list-disc [&_ol]:my-1 [&_ol]:pl-4 [&_ol]:list-decimal [&_li]:my-0",
  "[&_code]:bg-elevated [&_code]:px-1 [&_code]:rounded [&_code]:font-mono [&_code]:text-[0.9em]",
  "[&_a]:text-accent [&_a]:underline",
  "[&_strong]:font-semibold [&_strong]:text-text-primary",
].join(" ");

export function MarkdownRenderer({ content, variant = "full", className }: MarkdownRendererProps) {
  const remarkPlugins = variant === "compact" ? [remarkGfm, remarkBreaks] : [remarkGfm];

  return (
    <div className={cn(variant === "inline" ? INLINE_CLASSES : PROSE_CLASSES, className)}>
      <ReactMarkdown remarkPlugins={remarkPlugins}>{content}</ReactMarkdown>
    </div>
  );
}
