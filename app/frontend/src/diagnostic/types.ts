// Types de l'API de diagnostic (backend : diagnostic.py, ingestion.py, aggregation.py,
// maintenance.py, planning/scheduler.py). Dates en texte ISO 8601, UTC.

import type { Issue, Role } from "../home/types";

export interface EntityStatus {
  entity_id: string;
  role: Role;
  last_value: number | null;
  last_time: string | null;
  received: number;
  kept: number;
}

export interface IngestionStatus {
  running: boolean;
  entities: EntityStatus[];
  received: number;
  written: number;
  pending: number;
  last_batch_at: string | null;
  last_error: string | null;
  days: string[];
  backfilled: number;
  last_backfill_at: string | null;
}

export interface HistoryStatus {
  imported: number;
  pending: string[];
  without_statistics: string[];
  since: Record<string, string>;
}

export interface AggregationStatus {
  running: boolean;
  last_run_at: string | null;
  written: number;
  complete_until: Record<string, string>;
  last_error: string | null;
  history: HistoryStatus;
}

export interface MaintenanceRun {
  started_at: string;
  duration_s: number;
  removed_days: string[];
  kept_days: string[];
  removed_aggregates: Record<string, number>;
}

export interface MaintenanceStatus {
  running: boolean;
  in_progress: boolean;
  next_run_at: string | null;
  last_run: MaintenanceRun | null;
  last_error: string | null;
  retention: { raw_days: number; quarter_days: number; hour_days: number | null };
  disk: { raw_bytes: number; graph_bytes: number; database_bytes: number };
}

export interface RunReport {
  day: string;
  started_at: string;
  manual: boolean;
  seconds_today: number;
  seconds_tomorrow: number | null;
  seconds_horizon: number | null;
  horizon_days: number;
  errors: string[];
}

export interface PlanningStatus {
  running: boolean;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  last_report: RunReport | null;
  last_error: string | null;
}

export interface DeviceIssue {
  device: string;
  entity_id: string | null;
  issue: Issue;
}

export interface Diagnostic {
  generated_at: string;
  memory_bytes: number | null;
  started_at: string | null;
  written_bytes: number | null;
  ingestion: IngestionStatus | null;
  today: Record<string, number>;
  aggregation: AggregationStatus | null;
  maintenance: MaintenanceStatus | null;
  planning: PlanningStatus | null;
  issues: DeviceIssue[] | null;
}
