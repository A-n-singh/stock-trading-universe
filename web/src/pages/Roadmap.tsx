import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useRoadmap } from "../api";
import { Card, Loading, PageHeader } from "../components/ui";

export default function Roadmap() {
  const q = useRoadmap();
  return (
    <>
      <PageHeader title="Roadmap" subtitle="Findings so far, what's built, and the agreed next steps." />
      <Card>
        {q.isLoading ? <Loading /> : (
          <article className="prose prose-invert max-w-none prose-headings:tracking-tight prose-a:text-accent prose-table:text-sm prose-th:text-ink-2">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{q.data?.markdown ?? ""}</ReactMarkdown>
          </article>
        )}
      </Card>
    </>
  );
}
