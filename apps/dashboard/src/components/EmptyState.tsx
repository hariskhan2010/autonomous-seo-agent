export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-neutral-300 dark:border-neutral-700 p-8 text-center text-sm text-neutral-500 dark:text-neutral-400">
      {children}
    </div>
  );
}
