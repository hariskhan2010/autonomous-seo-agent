// Shapes returned by the FastAPI backend (apps/api). Kept hand-written and minimal rather than
// codegen'd from an OpenAPI schema — the API surface here is small and stable enough that a
// generator would be more ceremony than value right now.

export interface Project {
  id: string;
  name: string;
  slug: string;
  business_goal: string | null;
  approval_mode: "read_only" | "assisted" | "autonomous";
  config: Record<string, unknown>;
  created_at: string;
}

export interface Opportunity {
  id: string;
  type: string;
  title: string;
  url: string | null;
  priority: "P0" | "P1" | "P2" | "P3";
  score: number;
  status: string;
  action_class: string;
  recommendation: string | null;
  expected_outcome: string | null;
  seen_count: number;
}

export interface EvidenceRow {
  evidence_id: string;
  kind: string;
  source_url: string | null;
  provider: string;
  content_hash: string;
  confidence: number | null;
  collected_at: string;
}

export interface PlanSummary {
  id: string;
  state: string;
  requires_approval: boolean;
  max_action_class: string;
  created_at: string;
}

export interface PlanStep {
  ordinal: number;
  objective: string;
  tool: string;
  action_class: string;
  permission: string;
  verification: Record<string, unknown> | null;
  rollback: Record<string, unknown> | null;
  depends_on: number[] | null;
}

export interface PlanDetail {
  id: string;
  opportunity_id: string;
  state: string;
  root_cause: string | null;
  chosen_solution: string | null;
  requires_approval: boolean;
  max_action_class: string;
  steps: PlanStep[];
}

export interface Change {
  id: string;
  adapter: string;
  state: string;
  target: string;
  action_class: string;
  external_ref: string | null;
  rollback_strategy: string;
  verified: boolean;
  applied_at: string | null;
}

export interface Issue {
  id: string;
  check_code: string;
  category: string;
  severity: string;
  title: string;
  url: string | null;
  fix: string | null;
  seen_count: number;
}

export interface CrawlRun {
  id: string;
  website_id: string;
  state: string;
  tier: string;
  stats: Record<string, unknown>;
  finished_at: string | null;
}

export interface Anomaly {
  id: string;
  metric: string;
  direction: "drop" | "spike";
  magnitude_pct: number;
  detected_on: string;
  investigation: Record<string, unknown>;
}

export interface Experiment {
  id: string;
  type: string;
  hypothesis: string;
  state: string;
  verdict: string | null;
  confidence: number | null;
  result: Record<string, unknown> | null;
  confounders: unknown;
}
