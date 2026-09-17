import { api } from "@/lib/api";
import type { Issue } from "@/lib/types";
import { SeverityBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";

export default async function IssuesPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const issues = await api.get<Issue[]>(`/v1/issues?project_id=${projectId}`);

  if (issues.length === 0) {
    return <EmptyState>No open technical issues.</EmptyState>;
  }

  return (
    <ul className="divide-y divide-neutral-200 dark:divide-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-800">
      {issues.map((i) => (
        <li key={i.id} className="px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="font-medium truncate">{i.title}</div>
              <div className="text-xs text-neutral-500 truncate">
                {i.check_code} · {i.category}
                {i.url ? ` · ${i.url}` : ""} · seen {i.seen_count}×
              </div>
            </div>
            <SeverityBadge severity={i.severity} />
          </div>
          {i.fix ? (
            <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1">{i.fix}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
