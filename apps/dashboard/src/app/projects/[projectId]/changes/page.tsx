import { api } from "@/lib/api";
import type { Change } from "@/lib/types";
import { StateBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";

export default async function ChangesPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const changes = await api.get<Change[]>(`/v1/changes?project_id=${projectId}`);

  if (changes.length === 0) {
    return <EmptyState>No changes have been applied yet.</EmptyState>;
  }

  return (
    <ul className="divide-y divide-neutral-200 dark:divide-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-800">
      {changes.map((c) => (
        <li key={c.id} className="px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="font-medium truncate">{c.target}</div>
              <div className="text-xs text-neutral-500">
                {c.adapter} · {c.rollback_strategy} rollback
                {c.applied_at ? ` · applied ${new Date(c.applied_at).toLocaleString()}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {c.verified ? (
                <span className="text-xs rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 px-2.5 py-0.5">
                  verified
                </span>
              ) : (
                <span className="text-xs rounded-full bg-neutral-100 text-neutral-500 dark:bg-neutral-800 px-2.5 py-0.5">
                  unverified
                </span>
              )}
              <StateBadge state={c.state} />
            </div>
          </div>
          {c.external_ref ? (
            <a
              href={c.external_ref}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline break-all"
            >
              {c.external_ref}
            </a>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
