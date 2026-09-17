import Link from "next/link";
import { revalidatePath } from "next/cache";
import { api, ApiError } from "@/lib/api";
import type { PlanDetail } from "@/lib/types";
import { StateBadge } from "@/components/Badge";

async function decidePlan(projectId: string, planId: string, formData: FormData) {
  "use server";
  const decision = String(formData.get("decision"));
  const note = String(formData.get("note") ?? "").trim();
  await api.post(`/v1/plans/${planId}/approve`, { decision, note });
  revalidatePath(`/projects/${projectId}/plans/${planId}`);
}

export default async function PlanDetailPage({
  params,
}: {
  params: Promise<{ projectId: string; planId: string }>;
}) {
  const { projectId, planId } = await params;

  let plan: PlanDetail;
  try {
    plan = await api.get<PlanDetail>(`/v1/plans/${planId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return <p className="text-sm text-neutral-500">Plan not found.</p>;
    }
    throw e;
  }

  const boundDecide = decidePlan.bind(null, projectId, planId);
  const canDecide = plan.state === "awaiting_approval";

  return (
    <div className="space-y-8">
      <div>
        <Link
          href={`/projects/${projectId}/opportunities/${plan.opportunity_id}`}
          className="text-xs text-neutral-500 hover:underline"
        >
          ← Opportunity
        </Link>
        <div className="flex items-center gap-2 mt-2">
          <h2 className="text-lg font-semibold">Plan</h2>
          <StateBadge state={plan.state} />
        </div>
        <p className="text-xs text-neutral-500 mt-1">
          max action class: <code>{plan.max_action_class}</code> · requires approval:{" "}
          {plan.requires_approval ? "yes" : "no"}
        </p>
      </div>

      {plan.root_cause ? (
        <section>
          <h3 className="text-sm font-medium mb-1">Root cause</h3>
          <p className="text-sm text-neutral-700 dark:text-neutral-300">{plan.root_cause}</p>
        </section>
      ) : null}

      {plan.chosen_solution ? (
        <section>
          <h3 className="text-sm font-medium mb-1">Chosen solution</h3>
          <p className="text-sm text-neutral-700 dark:text-neutral-300">{plan.chosen_solution}</p>
        </section>
      ) : null}

      <section>
        <h3 className="text-sm font-medium mb-2">Steps</h3>
        <ol className="space-y-2">
          {plan.steps.map((step) => (
            <li
              key={step.ordinal}
              className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {step.ordinal}. {step.objective}
                </span>
                <span className="text-xs rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5">
                  {step.action_class}
                </span>
              </div>
              <div className="text-xs text-neutral-500 mt-1">
                tool: <code>{step.tool}</code> · permission: {step.permission}
                {step.depends_on && step.depends_on.length > 0
                  ? ` · depends on: ${step.depends_on.join(", ")}`
                  : ""}
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-5">
        <h3 className="text-sm font-medium mb-3">Decision</h3>
        {!canDecide ? (
          <p className="text-sm text-neutral-500">
            This plan is <StateBadge state={plan.state} /> — no decision needed right now.
          </p>
        ) : (
          <form action={boundDecide} className="space-y-3">
            <textarea
              name="note"
              required
              placeholder="Note (required) — why you're approving or rejecting this"
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-2 text-sm"
              rows={3}
            />
            <div className="flex gap-3">
              <button
                type="submit"
                name="decision"
                value="approved"
                className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
              >
                Approve
              </button>
              <button
                type="submit"
                name="decision"
                value="rejected"
                className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700"
              >
                Reject
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
