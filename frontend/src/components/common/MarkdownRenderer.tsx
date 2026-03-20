import ReactMarkdown from "react-markdown";

interface MarkdownRendererProps {
  content: string;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <div className="prose prose-invert prose-sm max-w-none [&_h1]:text-text-primary [&_h2]:text-text-primary [&_h3]:text-text-primary [&_p]:text-text-secondary [&_li]:text-text-secondary [&_code]:bg-elevated [&_code]:px-1 [&_code]:rounded [&_pre]:bg-elevated [&_pre]:border [&_pre]:border-border [&_a]:text-accent [&_strong]:text-text-primary [&_table]:border-border [&_th]:border-border [&_td]:border-border">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
