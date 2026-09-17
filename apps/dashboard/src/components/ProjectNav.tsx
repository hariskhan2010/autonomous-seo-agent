"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "", label: "Overview" },
  { href: "/opportunities", label: "Opportunities" },
  { href: "/issues", label: "Issues" },
  { href: "/changes", label: "Changes" },
];

export function ProjectNav({ projectId }: { projectId: string }) {
  const pathname = usePathname();
  const base = `/projects/${projectId}`;

  return (
    <nav className="flex gap-1 border-b border-neutral-200 dark:border-neutral-800 mb-6">
      {TABS.map((tab) => {
        const href = `${base}${tab.href}`;
        const isActive = tab.href === "" ? pathname === base : pathname.startsWith(href);
        return (
          <Link
            key={tab.label}
            href={href}
            className={`px-3 py-2 text-sm border-b-2 -mb-px ${
              isActive
                ? "border-neutral-900 dark:border-neutral-100 font-medium"
                : "border-transparent text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
