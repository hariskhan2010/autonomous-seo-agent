import Link from "next/link";
import { api } from "@/lib/api";
import type { Opportunity, EvidenceRow, PlanSummary } from "@/lib/types";
import { PriorityBadge, StateBadge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ projectId: string; opportunityId: string }>;
}) {
  const { projectId, opportunityId } = await params;

  const [opportunities, evidence, plans] = await Promise.all([
    api.get<Opportunity[]>(`/v1/opportunities?project_id=${projectId}`),
    api.get<EvidenceRow[]>(`/v1/opportunities/${opportunityId}/evidence`),
    api.get<PlanSummary[]>(`/v1/opportunities/${opportunityId}/plans`),
  ]);
  const opportunity = opportunities.find((o) => o.id === opportunityId);

  if (!opportunity) {
    return (
      <div>
        <Link href={`/projects/${projectId}/opportunities`} className="text-xs text-neutral-500 hover:underline">
          ← Opportunities
        </Link>
        <p className="mt-4 text-sm text-neutral-500">Opportunity not found.</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <Link href={`/projects/${projectId}/opportunities`} className="text-xs text-neutral-500 hover:underline">
          ← Opportunities
        </Link>
        <div className="flex items-center gap-2 mt-2">
          <h2 className="text-lg font-semibold">{opportunity.title}</h2>
          <PriorityBadge priority={opportunity.priority} />
          <StateBadge state={opportunity.status} />
        </div>
        <p className="text-sm text-neutral-500 mt-1">
          {opportunity.type} {opportunity.url ? `· ${opportunity.url}` : ""} · score{" "}
          {opportunity.score.toFixed(2)} · seen {opportunity.seen_count}×
        </p>
      </div>

      {opportunity.recommendation ? (
        <section>
          <h3 className="text-sm font-medium mb-1">Recommendation</h3>
          <p className="text-sm text-neutral-700 dark:text-neutral-300">{opportunity.recommendation}</p>
        </section>
      ) : null}

      {opportunity.expected_outcome ? (
        <section>
          <h3 className="text-sm font-medium mb-1">Expected outcome</h3>
          <p className="text-sm text-neutral-700 dark:text-neutral-300">{opportunity.expected_outcome}</p>
        </section>
      ) : null}

      <section>
        <h3 className="text-sm font-medium mb-2">Plans</h3>
        {plans.length === 0 ? (
          <EmptyState>No plan has been built for this opportunity yet.</EmptyState>
        ) : (
          <ul className="divide-y divide-neutral-200 dark:divide-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-800">
            {plans.map((p) => (
              <li key={p.id}>
                <Link
                  href={`/projects/${projectId}/plans/${p.id}`}
                  className="flex items-center justify-between px-4 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-900"
                >
                  <span className="text-xs text-neutral-500">
                    {new Date(p.created_at).toLocaleString()}
                  </span>
                  <StateBadge state={p.state} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-sm font-medium mb-2">Evidence ({evidence.length})</h3>
        {evidence.length === 0 ? (
          <EmptyState>No evidence linked — this shouldn&apos;t happen; every opportunity must cite evidence.</EmptyState>
        ) : (
          <ul className="space-y-2">
            {evidence.map((e) => (
              <li
                key={e.evidence_id}
                className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{e.kind}</span>
                  <span className="text-xs text-neutral-500">
                    {e.confidence !== null ? `${Math.round(e.confidence * 100)}% confidence` : ""}
                  </span>
                </div>
                <div className="text-xs text-neutral-500 mt-1">
                  {e.provider} · {new Date(e.collected_at).toLocaleString()}
                </div>
                {e.source_url ? (
                  <a
                    href={e.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-600 dark:text-blue-400 hover:underline break-all"
                  >
                    {e.source_url}
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
