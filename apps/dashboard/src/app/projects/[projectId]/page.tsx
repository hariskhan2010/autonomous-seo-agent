import { revalidatePath } from "next/cache";
import { api } from "@/lib/api";
import type { Opportunity, Issue, Change, Project } from "@/lib/types";

async function setApprovalMode(projectId: string, formData: FormData) {
  "use server";
  const approval_mode = String(formData.get("approval_mode"));
  await api.patch(`/v1/projects/${projectId}`, { approval_mode });
  revalidatePath(`/projects/${projectId}`);
}

export default async function ProjectOverviewPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const [project, opportunities, issues, changes] = await Promise.all([
    api.get<Project>(`/v1/projects/${projectId}`),
    api.get<Opportunity[]>(`/v1/opportunities?project_id=${projectId}`),
    api.get<Issue[]>(`/v1/issues?project_id=${projectId}`),
    api.get<Change[]>(`/v1/changes?project_id=${projectId}`),
  ]);

  const openOpportunities = opportunities.filter(
    (o) => !["completed", "ignored", "rolled_back"].includes(o.status),
  );
  const awaitingApproval = opportunities.filter((o) => o.status === "awaiting_approval");

  const boundSetApprovalMode = setApprovalMode.bind(null, projectId);

  return (
    <div className="space-y-8">
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Tile label="Open opportunities" value={openOpportunities.length} />
        <Tile label="Awaiting approval" value={awaitingApproval.length} accent={awaitingApproval.length > 0} />
        <Tile label="Open issues" value={issues.length} />
        <Tile label="Recent changes" value={changes.length} />
      </section>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-5">
        <h2 className="text-sm font-medium mb-1">Approval mode — kill switch</h2>
        <p className="text-xs text-neutral-500 mb-4">
          <code>read_only</code> blocks every write immediately, including plans already awaiting
          approval. <code>assisted</code> requires a human decision on every write.{" "}
          <code>autonomous</code> auto-approves only allow-listed low-risk change types.
        </p>
        <form action={boundSetApprovalMode} className="flex items-center gap-3">
          <select
            name="approval_mode"
            defaultValue={project.approval_mode}
            className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
          >
            <option value="read_only">read_only</option>
            <option value="assisted">assisted</option>
            <option value="autonomous">autonomous</option>
          </select>
          <button
            type="submit"
            className="rounded-md bg-neutral-900 dark:bg-neutral-100 px-4 py-1.5 text-sm font-medium text-white dark:text-neutral-900"
          >
            Update
          </button>
        </form>
      </section>
    </div>
  );
}

function Tile({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        accent
          ? "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40"
          : "border-neutral-200 dark:border-neutral-800"
      }`}
    >
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-neutral-500 mt-1">{label}</div>
    </div>
  );
}
