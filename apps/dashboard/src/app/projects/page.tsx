import Link from "next/link";
import { revalidatePath } from "next/cache";
import { api, ApiError } from "@/lib/api";
import type { Project } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";

async function createProject(formData: FormData) {
  "use server";
  const name = String(formData.get("name") ?? "").trim();
  const slug = String(formData.get("slug") ?? "").trim();
  if (!name || !slug) return;
  await api.post<Project>("/v1/projects", { name, slug });
  revalidatePath("/projects");
}

export default async function ProjectsPage() {
  let projects: Project[] = [];
  let error: string | null = null;
  try {
    projects = await api.get<Project[]>("/v1/projects");
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Could not reach the API";
  }

  return (
    <div className="mx-auto max-w-3xl w-full px-6 py-10">
      <h1 className="text-2xl font-semibold mb-1">Projects</h1>
      <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-8">
        The approval console — opportunities, plans, and changes for each project.
      </p>

      {error ? (
        <div className="mb-8 rounded-lg border border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40 p-4 text-sm text-red-800 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <form
        action={createProject}
        className="mb-10 flex flex-wrap items-end gap-3 rounded-lg border border-neutral-200 dark:border-neutral-800 p-4"
      >
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500" htmlFor="name">
            Name
          </label>
          <input
            id="name"
            name="name"
            required
            className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            placeholder="Acme Corp"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500" htmlFor="slug">
            Slug
          </label>
          <input
            id="slug"
            name="slug"
            required
            pattern="[a-z0-9][a-z0-9-]*"
            className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            placeholder="acme-corp"
          />
        </div>
        <button
          type="submit"
          className="rounded-md bg-neutral-900 dark:bg-neutral-100 px-4 py-1.5 text-sm font-medium text-white dark:text-neutral-900"
        >
          Create project
        </button>
      </form>

      {projects.length === 0 && !error ? (
        <EmptyState>No projects yet — create one above.</EmptyState>
      ) : (
        <ul className="divide-y divide-neutral-200 dark:divide-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-800">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-900"
              >
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-neutral-500">{p.slug}</div>
                </div>
                <span className="text-xs rounded-full bg-neutral-100 dark:bg-neutral-800 px-2.5 py-0.5">
                  {p.approval_mode}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
