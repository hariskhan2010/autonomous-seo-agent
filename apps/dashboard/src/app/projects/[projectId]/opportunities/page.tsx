import Link from "next/link";
import { api } from "@/lib/api";
import type { Opportunity } from "@/lib/types";
import { PriorityBadge, StateBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";

const PRIORITIES = ["P0", "P1", "P2", "P3"];

export default async function OpportunitiesPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ priority?: string; status?: string }>;
}) {
  const { projectId } = await params;
  const { priority, status } = await searchParams;

  const qs = new URLSearchParams({ project_id: projectId });
  if (priority) qs.set("priority", priority);
  if (status) qs.set("status", status);

  const opportunities = await api.get<Opportunity[]>(`/v1/opportunities?${qs.toString()}`);

  function filterHref(next: Partial<{ priority: string; status: string }>) {
    const p = new URLSearchParams();
    const merged = { priority, status, ...next };
    if (merged.priority) p.set("priority", merged.priority);
    if (merged.status) p.set("status", merged.status);
    const query = p.toString();
    return `/projects/${projectId}/opportunities${query ? `?${query}` : ""}`;
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-6">
        <span className="text-xs text-neutral-500 mr-1">Priority:</span>
        <Link
          href={filterHref({ priority: undefined })}
          className={`text-xs rounded-full px-2.5 py-1 ${!priority ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900" : "bg-neutral-100 dark:bg-neutral-800"}`}
        >
          All
        </Link>
        {PRIORITIES.map((pr) => (
          <Link
            key={pr}
            href={filterHref({ priority: pr })}
            className={`text-xs rounded-full px-2.5 py-1 ${priority === pr ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900" : "bg-neutral-100 dark:bg-neutral-800"}`}
          >
            {pr}
          </Link>
        ))}
        <span className="text-xs text-neutral-500 ml-3 mr-1">Status:</span>
        <Link
          href={filterHref({ status: "awaiting_approval" })}
          className={`text-xs rounded-full px-2.5 py-1 ${status === "awaiting_approval" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900" : "bg-neutral-100 dark:bg-neutral-800"}`}
        >
          Awaiting approval
        </Link>
      </div>

      {opportunities.length === 0 ? (
        <EmptyState>No opportunities match this filter.</EmptyState>
      ) : (
        <ul className="divide-y divide-neutral-200 dark:divide-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-800">
          {opportunities.map((o) => (
            <li key={o.id}>
              <Link
                href={`/projects/${projectId}/opportunities/${o.id}`}
                className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-900"
              >
                <div className="min-w-0">
                  <div className="font-medium truncate">{o.title}</div>
                  <div className="text-xs text-neutral-500 truncate">
                    {o.type} {o.url ? `· ${o.url}` : ""}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-xs text-neutral-500 tabular-nums">
                    {o.score.toFixed(2)}
                  </span>
                  <StateBadge state={o.status} />
                  <PriorityBadge priority={o.priority} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
