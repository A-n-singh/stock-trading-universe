import { Brain } from "lucide-react";
import { useMemory } from "../api";
import { Badge, Card, Empty, Loading, PageHeader, Stat } from "../components/ui";

export default function Memory() {
  const q = useMemory();
  const recs = q.data?.memory.records ?? [];
  const lessons = recs.filter((r) => r.kind === "pattern");
  const notes = recs.filter((r) => r.kind !== "pattern");
  const tasks = q.data?.refinements.tasks ?? [];

  return (
    <>
      <PageHeader title="Memory" subtitle="What the system has learned from its own trades. Lessons need real trades as proof, and a lesson that keeps failing retires itself." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Team-lead lessons" value={lessons.length} />
        <Stat label="Coin notes" value={notes.length} />
        <Stat label="Retired lessons" value={lessons.filter((l) => l.retired_at).length} />
        <Stat label="Refinement tasks" value={tasks.length} />
      </div>
      {q.isLoading ? <Loading /> : (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card title="Lessons (team-lead shelves)" pad={false}>
            {lessons.length ? (
              <ul className="divide-y divide-line">
                {lessons.map((l) => {
                  const wins = l.outcomes.filter((o) => o[1]).length;
                  return (
                    <li key={l.id} className="px-5 py-3">
                      <div className="text-sm">{l.text}</div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        <Badge tone="info">{l.owner_id} desk</Badge>
                        <Badge>{l.evidence.length} proofs</Badge>
                        <Badge tone={wins * 2 >= l.outcomes.length ? "up" : "down"}>{wins}/{l.outcomes.length} later trades won</Badge>
                        {l.retired_at && <Badge tone="down">retired</Badge>}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : <Empty icon={<Brain className="size-8" />} title="No lessons yet">A lesson is written once a team lead has at least 3 finished trades of one kind with a clear result.</Empty>}
          </Card>
          <Card title="Coin notes" pad={false}>
            {notes.length ? (
              <ul className="divide-y divide-line">
                {notes.map((n) => <li key={n.id} className="px-5 py-3 text-sm"><Badge tone="info">{n.owner_id}</Badge> <span className="ml-2 text-ink-2">{n.text}</span></li>)}
              </ul>
            ) : <Empty title="No coin notes yet" />}
          </Card>
          <Card title="Refinement tasks (clusters that kept losing)" className="lg:col-span-2" pad={false}>
            {tasks.length ? (
              <ul className="divide-y divide-line">
                {tasks.map((t, i) => (
                  <li key={i} className="flex flex-wrap gap-3 px-5 py-3 text-sm">
                    <Badge tone="warn">{String(t.lead)} desk</Badge>
                    <span className="text-ink-2">{String(t.event_type)} news on {String(t.sector)} coins lost {String(t.losses)} of {String(t.sample)} trades → {String(t.action)}</span>
                  </li>
                ))}
              </ul>
            ) : <Empty title="No refinements needed" />}
          </Card>
        </div>
      )}
    </>
  );
}
