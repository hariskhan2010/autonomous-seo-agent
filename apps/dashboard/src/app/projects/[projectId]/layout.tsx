import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { Project } from "@/lib/types";
import { ProjectNav } from "@/components/ProjectNav";

export default async function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  let project: Project | null = null;
  try {
    project = await api.get<Project>(`/v1/projects/${projectId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return (
        <div className="mx-auto max-w-3xl w-full px-6 py-10">
          <p className="text-sm text-neutral-500">
            Project not found. <Link href="/projects" className="underline">Back to projects</Link>
          </p>
        </div>
      );
    }
    throw e;
  }

  return (
    <div className="mx-auto max-w-5xl w-full px-6 py-10">
      <div className="mb-6">
        <Link href="/projects" className="text-xs text-neutral-500 hover:underline">
          ← All projects
        </Link>
        <h1 className="text-2xl font-semibold mt-1">{project.name}</h1>
      </div>
      <ProjectNav projectId={projectId} />
      {children}
    </div>
  );
}
