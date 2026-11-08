// Types de l'API de diagnostic (backend : diagnostic.py, ingestion.py, aggregation.py,
// maintenance.py, planning/scheduler.py). Dates en texte ISO 8601, UTC.

import type { Issue, Role } from "../home/types";

export interface EntityStatus {
  entity_id: string;
  role: Role;
  last_value: number | null;
  last_time: string | null;
  last_seen?: string | null; // dernier signe de vie, valeur inchangée comprise
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

export interface Resources {
  cpu_percent: number | null; // moyenne sur 15 min, en % d'un cœur
  cpu_peak_percent: number | null; // minute la plus chargée des dernières 24 h
  cpu_cores: number | null;
  memory_bytes: number | null;
  memory_peak_bytes: number | null;
  memory_floor_bytes?: number | null; // plus bas des 15 dernières minutes
  memory_limit_bytes: number | null; // limite du conteneur, sinon mémoire de la machine
  memory_limit_source?: "container" | "machine" | null;
  disk_used_bytes: number | null; // dossier des données de l'application
  disk_free_bytes: number | null;
  disk_total_bytes: number | null;
  disk_backup_bytes?: number | null; // place qu'une sauvegarde demande
  memory_alert_bytes?: number | null; // seuil d'alerte (ligne rouge) : mémoire au-delà
  disk_alert_free_bytes?: number | null; // seuil d'alerte : espace libre en deçà
  measured_s: number; // durée couverte par les relevés
}

export interface ResourcePoint {
  time: string; // fin de la minute
  cpu_percent: number | null; // charge de la minute, en % d'un cœur
  memory_bytes: number | null;
  disk_free_bytes: number | null;
}

export interface Diagnostic {
  generated_at: string;
  memory_bytes: number | null;
  started_at: string | null;
  written_bytes: number | null;
  ingestion: IngestionStatus | null;
  today: Record<string, number>;
  silent?: string[]; // entités muettes à valeur figée suspecte (règle du serveur)
  aggregation: AggregationStatus | null;
  maintenance: MaintenanceStatus | null;
  planning: PlanningStatus | null;
  issues: DeviceIssue[] | null;
  resources?: Resources | null;
}
