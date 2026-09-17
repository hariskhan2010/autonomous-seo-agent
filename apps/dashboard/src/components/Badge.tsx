const PRIORITY_STYLES: Record<string, string> = {
  P0: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  P1: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  P2: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  P3: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
};

const STATE_STYLES: Record<string, string> = {
  detected: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  planned: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  awaiting_approval: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  executing: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  verifying: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  applied: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  rolled_back: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  ignored: "bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400",
};

const DEFAULT_STYLE = "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";

function pill(label: string, className: string) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${className}`}
    >
      {label}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: string }) {
  return pill(priority, PRIORITY_STYLES[priority] ?? DEFAULT_STYLE);
}

export function StateBadge({ state }: { state: string }) {
  return pill(state.replace(/_/g, " "), STATE_STYLES[state] ?? DEFAULT_STYLE);
}

export function SeverityBadge({ severity }: { severity: string }) {
  const styles: Record<string, string> = {
    critical: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
    high: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
    medium: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
    low: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  };
  return pill(severity, styles[severity] ?? DEFAULT_STYLE);
}
