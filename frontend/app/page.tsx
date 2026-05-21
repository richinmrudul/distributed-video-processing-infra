"use client";

import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

type VideoJobStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED" | string;

type UploadResponse = {
  id: string;
  idempotency_key: string | null;
  status: VideoJobStatus;
  original_filename: string;
  raw_path: string | null;
  storage_backend: string;
  raw_object_key: string | null;
  processed_object_key: string | null;
  thumbnail_object_key: string | null;
  queue_job_id: string | null;
  attempt_count: number;
  max_attempts: number;
};

type StatusResponse = UploadResponse & {
  processed_path: string | null;
  thumbnail_path: string | null;
  error_message: string | null;
  failed_at: string | null;
  last_error_type: string | null;
  retry_exhausted: boolean;
  manually_retried_at: string | null;
  manual_retry_count: number;
  processing_started_at: string | null;
  processing_completed_at: string | null;
  processing_duration_seconds: number | null;
  created_at: string;
  updated_at: string;
};

type AssetsResponse = {
  video_id: string;
  storage_backend: string;
  status: VideoJobStatus;
  expires_in_seconds: number;
  raw_url: string | null;
  processed_url: string | null;
  thumbnail_url: string | null;
};

type FailedJob = {
  id: string;
  original_filename: string;
  status: VideoJobStatus;
  retry_exhausted: boolean;
  last_error_type: string | null;
  failed_at: string | null;
};

type StuckJob = {
  id: string;
  status: VideoJobStatus;
  stuck_reason: string;
  age_seconds: number;
};

type RecoveryResult = {
  inspected_count: number;
  recovered_count: number;
  failed_count: number;
  skipped_count: number;
};

type QueueHealth = {
  redis_connected: boolean;
  queue_name: string;
  queued_jobs_count: number;
  worker_count: number;
  queue_pressure_level: string;
  redis_error?: string | null;
};

type StorageHealth = {
  backend_configured?: boolean;
  storage_backend?: string;
  endpoint?: string | null;
  public_endpoint?: string | null;
  expected_buckets?: string[];
  buckets?: Record<string, boolean>;
  connected?: boolean;
  error?: string | null;
  status?: string;
  healthy?: boolean;
};

type ApiFailure = {
  message: string;
  reason: string | null;
  statusCode: number;
};

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

const statusStyles: Record<string, string> = {
  QUEUED: "border-slate-600/60 bg-slate-800/80 text-slate-200",
  PROCESSING: "border-blue-400/40 bg-blue-500/15 text-blue-200",
  COMPLETED: "border-emerald-400/40 bg-emerald-500/15 text-emerald-200",
  FAILED: "border-rose-400/40 bg-rose-500/15 text-rose-200"
};

const statusDotStyles: Record<string, string> = {
  QUEUED: "bg-slate-400",
  PROCESSING: "bg-blue-500",
  COMPLETED: "bg-emerald-500",
  FAILED: "bg-rose-500"
};

function statusClass(status: string) {
  return statusStyles[status] || "border-slate-600/60 bg-slate-800/80 text-slate-200";
}

function statusDotClass(status: string) {
  return statusDotStyles[status] || "bg-zinc-400";
}

function formatSeconds(value: number | null | undefined) {
  return typeof value === "number" ? `${value.toFixed(2)}s` : "not available";
}

function formatLatency(value: number | null) {
  if (value === null) return "not available";
  return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(2)}s`;
}

function httpStatusLabel(statusCode: number | null) {
  const labels: Record<number, string> = {
    200: "200 OK",
    201: "201 Created",
    429: "429 Too Many Requests",
    503: "503 Service Unavailable"
  };
  if (!statusCode) return "not available";
  return labels[statusCode] || `${statusCode}`;
}

function uploadOutcomeLabel(statusCode: number | null) {
  if (statusCode === 201) return "New job created";
  if (statusCode === 200) return "Existing idempotent job reused";
  if (statusCode && (statusCode < 200 || statusCode >= 300)) return "Upload rejected";
  return "Upload result";
}

function valueOrFallback(value: ReactNode) {
  return value === null || value === undefined || value === "" ? "not available" : value;
}

async function readApiError(response: Response): Promise<ApiFailure> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    const reason = typeof detail?.reason === "string" ? detail.reason : typeof body?.reason === "string" ? body.reason : null;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail?.message === "string"
          ? detail.message
          : typeof detail?.reason === "string"
            ? detail.reason
            : typeof body?.message === "string"
              ? body.message
              : JSON.stringify(body);
    return { message, reason, statusCode: response.status };
  } catch {
    return { message: `${response.status} ${response.statusText}`, reason: null, statusCode: response.status };
  }
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [assets, setAssets] = useState<AssetsResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<ApiFailure | null>(null);
  const [uploadHttpStatus, setUploadHttpStatus] = useState<number | null>(null);
  const [uploadLatencyMs, setUploadLatencyMs] = useState<number | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [assetsError, setAssetsError] = useState<string | null>(null);

  const [queueHealth, setQueueHealth] = useState<QueueHealth | null>(null);
  const [storageHealth, setStorageHealth] = useState<StorageHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [adminKey, setAdminKey] = useState("");
  const [adminLoading, setAdminLoading] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [adminMessage, setAdminMessage] = useState<string | null>(null);
  const [failedJobs, setFailedJobs] = useState<FailedJob[]>([]);
  const [stuckJobs, setStuckJobs] = useState<StuckJob[]>([]);
  const [recovery, setRecovery] = useState<RecoveryResult | null>(null);

  const activeVideoId = status?.id || upload?.id || null;
  const terminal = status?.status === "COMPLETED" || status?.status === "FAILED";

  useEffect(() => {
    void loadHealth();
  }, []);

  useEffect(() => {
    if (!upload?.id || terminal) return;
    let cancelled = false;

    async function loadStatus() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/videos/${upload?.id}/status`);
        if (!response.ok) throw new Error((await readApiError(response)).message);
        const body = (await response.json()) as StatusResponse;
        if (!cancelled) {
          setStatus(body);
          setStatusError(null);
        }
      } catch (error) {
        if (!cancelled) setStatusError(error instanceof Error ? error.message : "Could not load status");
      }
    }

    void loadStatus();
    const timer = window.setInterval(loadStatus, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [upload?.id, terminal]);

  useEffect(() => {
    if (status?.status !== "COMPLETED" || !status.id) return;
    let cancelled = false;

    async function loadAssets() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/videos/${status?.id}/assets`);
        if (!response.ok) throw new Error((await readApiError(response)).message);
        const body = (await response.json()) as AssetsResponse;
        if (!cancelled) {
          setAssets(body);
          setAssetsError(null);
        }
      } catch (error) {
        if (!cancelled) setAssetsError(error instanceof Error ? error.message : "Could not load assets");
      }
    }

    void loadAssets();
    return () => {
      cancelled = true;
    };
  }, [status?.id, status?.status]);

  const currentStatus = useMemo(() => status?.status || upload?.status || "No job", [status?.status, upload?.status]);
  const pollingActive = Boolean(upload?.id && !terminal);

  async function loadHealth() {
    setHealthLoading(true);
    setHealthError(null);
    try {
      const [queueResponse, storageResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/v1/queue/health`),
        fetch(`${API_BASE_URL}/api/v1/storage/health`)
      ]);
      if (!queueResponse.ok) throw new Error(`Queue health: ${(await readApiError(queueResponse)).message}`);
      if (!storageResponse.ok) throw new Error(`Storage health: ${(await readApiError(storageResponse)).message}`);
      setQueueHealth((await queueResponse.json()) as QueueHealth);
      setStorageHealth((await storageResponse.json()) as StorageHealth);
    } catch (error) {
      setHealthError(error instanceof Error ? error.message : "Could not load system health");
    } finally {
      setHealthLoading(false);
    }
  }

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setUploadError({ message: "Choose a video file first.", reason: "missing_file", statusCode: 0 });
      return;
    }

    setUploading(true);
    setUploadError(null);
    setUploadHttpStatus(null);
    setUploadLatencyMs(null);
    setUpload(null);
    setStatus(null);
    setAssets(null);
    setStatusError(null);
    setAssetsError(null);

    const form = new FormData();
    form.append("file", file);
    const headers: HeadersInit = {};
    const key = idempotencyKey.trim();
    if (key) headers["Idempotency-Key"] = key;

    const startedAt = performance.now();
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/videos/upload`, {
        method: "POST",
        headers,
        body: form
      });
      setUploadHttpStatus(response.status);
      setUploadLatencyMs(performance.now() - startedAt);
      if (!response.ok) {
        setUploadError(await readApiError(response));
        return;
      }
      const body = (await response.json()) as UploadResponse;
      setUpload(body);
      setStatus(body as StatusResponse);
      void loadHealth();
    } catch (error) {
      setUploadLatencyMs(performance.now() - startedAt);
      setUploadError({ message: error instanceof Error ? error.message : "Upload failed", reason: null, statusCode: 0 });
    } finally {
      setUploading(false);
    }
  }

  async function adminFetch<T>(path: string, options: RequestInit = {}) {
    if (!adminKey.trim()) throw new Error("Enter the admin key before calling operator endpoints.");
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        ...(options.headers || {}),
        "X-Admin-API-Key": adminKey.trim()
      }
    });
    if (!response.ok) throw new Error((await readApiError(response)).message);
    return (await response.json()) as T;
  }

  async function loadFailedJobs() {
    setAdminLoading("failed");
    setAdminError(null);
    setAdminMessage(null);
    try {
      const body = await adminFetch<{ jobs: FailedJob[] }>("/api/v1/jobs/failed");
      setFailedJobs(body.jobs);
      setAdminMessage(`Loaded ${body.jobs.length} failed job${body.jobs.length === 1 ? "" : "s"}.`);
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not load failed jobs");
    } finally {
      setAdminLoading(null);
    }
  }

  async function loadStuckJobs() {
    setAdminLoading("stuck");
    setAdminError(null);
    setAdminMessage(null);
    try {
      const body = await adminFetch<{ jobs: StuckJob[] }>("/api/v1/jobs/stuck");
      setStuckJobs(body.jobs);
      setAdminMessage(`Loaded ${body.jobs.length} stuck job${body.jobs.length === 1 ? "" : "s"}.`);
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not load stuck jobs");
    } finally {
      setAdminLoading(null);
    }
  }

  async function recoverStuckJobs() {
    setAdminLoading("recover");
    setAdminError(null);
    setAdminMessage(null);
    try {
      const body = await adminFetch<RecoveryResult>("/api/v1/jobs/recover-stuck", { method: "POST" });
      setRecovery(body);
      setAdminMessage("Recovery request completed.");
      try {
        const stuck = await adminFetch<{ jobs: StuckJob[] }>("/api/v1/jobs/stuck");
        setStuckJobs(stuck.jobs);
      } catch {
        // Keep the recovery result visible even if the refresh fails.
      }
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not recover stuck jobs");
    } finally {
      setAdminLoading(null);
    }
  }

  async function retryJob(videoId: string) {
    setRetryingJobId(videoId);
    setAdminError(null);
    setAdminMessage(null);
    try {
      await adminFetch<StatusResponse>(`/api/v1/jobs/${videoId}/retry`, { method: "POST" });
      setAdminMessage("Retry request queued.");
      const body = await adminFetch<{ jobs: FailedJob[] }>("/api/v1/jobs/failed");
      setFailedJobs(body.jobs);
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not retry job");
    } finally {
      setRetryingJobId(null);
    }
  }

  return (
    <main className="min-h-screen bg-[#080d1a] px-4 py-5 text-slate-100 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <Hero currentStatus={currentStatus} pollingActive={pollingActive} queueHealth={queueHealth} />

        <ArchitecturePipeline status={status?.status || upload?.status || null} hasUpload={Boolean(upload)} />

        <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="space-y-6">
            <Panel eyebrow="Client entrypoint" title="Public Upload Workflow" description="Submit videos through the public FastAPI endpoint with optional idempotency protection.">
              <UploadPanel
                file={file}
                idempotencyKey={idempotencyKey}
                uploading={uploading}
                uploadError={uploadError}
                uploadHttpStatus={uploadHttpStatus}
                uploadLatencyMs={uploadLatencyMs}
                upload={upload}
                onFileChange={setFile}
                onIdempotencyKeyChange={setIdempotencyKey}
                onSubmit={submitUpload}
              />
            </Panel>

            <Panel eyebrow="Infrastructure checks" title="Public System Health" description="Small public readiness checks for queue pressure, workers, and object storage.">
              <HealthSection
                queueHealth={queueHealth}
                storageHealth={storageHealth}
                healthLoading={healthLoading}
                healthError={healthError}
                onRefresh={loadHealth}
              />
            </Panel>
          </div>

          <div className="space-y-6">
            <JobStatusPanel
              activeVideoId={activeVideoId}
              currentStatus={currentStatus}
              pollingActive={pollingActive}
              status={status}
              statusError={statusError}
              upload={upload}
            />

            <AssetsPanel assets={assets} assetsError={assetsError} status={status} />
          </div>
        </div>

        <Panel eyebrow="Protected path" title="Operator Controls" description="Admin endpoints are protected with X-Admin-API-Key and are intended for recovery and inspection.">
          <AdminOperations
            adminKey={adminKey}
            adminLoading={adminLoading}
            retryingJobId={retryingJobId}
            adminError={adminError}
            adminMessage={adminMessage}
            failedJobs={failedJobs}
            stuckJobs={stuckJobs}
            recovery={recovery}
            onAdminKeyChange={setAdminKey}
            onLoadFailedJobs={loadFailedJobs}
            onLoadStuckJobs={loadStuckJobs}
            onRecoverStuckJobs={recoverStuckJobs}
            onRetryJob={retryJob}
          />
        </Panel>

        <Panel eyebrow="Runtime diagnostics" title="Platform Operations" description="Operational resources and reliability controls for inspecting the deployed video-processing platform.">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            <ReliabilityCapabilities />
            <div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <SystemLink label="API Docs" href="http://localhost:8000/docs" description="Inspect and test service contracts" />
                <SystemLink label="Grafana" href="http://localhost:3000" description="View service dashboards" />
                <SystemLink label="Prometheus" href="http://localhost:9090" description="Inspect metrics and targets" />
                <SystemLink label="Jaeger" href="http://localhost:16686" description="Trace distributed requests" />
                <SystemLink label="MinIO Console" href="http://localhost:9001" description="Inspect object-storage assets" />
              </div>
              <p className="mt-4 text-xs text-slate-500">Endpoints are shown for the local or port-forwarded operations surface.</p>
            </div>
          </div>
        </Panel>
      </div>
    </main>
  );
}

function Hero({ currentStatus, pollingActive, queueHealth }: { currentStatus: string; pollingActive: boolean; queueHealth: QueueHealth | null }) {
  const badges = ["Azure AKS", "FastAPI", "Redis/RQ", "FFmpeg Workers", "MinIO/S3", "PostgreSQL", "GHCR"];

  return (
    <header className="overflow-hidden rounded-[1.25rem] border border-white/10 bg-slate-950 shadow-2xl shadow-black/30">
      <div className="border-b border-white/10 bg-white/[0.025] px-5 py-3 sm:px-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {badges.map((badge) => (
              <span key={badge} className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-1 text-xs font-semibold text-slate-300 shadow-sm">
                {badge}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <RuntimeChip label="API" value={API_BASE_URL} />
            <RuntimeChip label="Workers" value={queueHealth?.worker_count ?? "n/a"} />
          </div>
        </div>
      </div>
      <div className="grid gap-7 bg-[radial-gradient(circle_at_15%_10%,rgba(59,130,246,0.16),transparent_32%),radial-gradient(circle_at_88%_18%,rgba(16,185,129,0.10),transparent_30%)] px-5 py-7 sm:px-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-200/80">Azure AKS demo | GHCR images</p>
          <h1 className="mt-3 max-w-4xl text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-5xl">
            Distributed Video Processing Console
          </h1>
          <p className="mt-4 max-w-3xl text-base leading-7 text-slate-300">
            A cloud-deployed async media pipeline that accepts uploads, queues work in Redis/RQ, processes video with FFmpeg workers, and serves short-lived MinIO/S3 assets.
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/25 p-4 text-white shadow-xl shadow-black/20 backdrop-blur">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">Current job</p>
              <div className="mt-3">
                <StatusBadge status={currentStatus} size="lg" />
              </div>
            </div>
            <div className={`mt-1 h-3 w-3 rounded-full shadow-lg ${pollingActive ? "bg-emerald-400 shadow-emerald-400/40" : "bg-slate-600 shadow-slate-700/40"}`} />
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
            <DarkMetric label="Queue pressure" value={queueHealth?.queue_pressure_level || "n/a"} />
            <DarkMetric label="Queued jobs" value={queueHealth?.queued_jobs_count ?? "n/a"} />
          </div>
          {pollingActive ? <p className="mt-4 text-xs text-emerald-200/80">Polling status every 2 seconds</p> : <p className="mt-4 text-xs text-slate-500">Polling starts after upload</p>}
        </div>
      </div>
    </header>
  );
}

function ArchitecturePipeline({ status, hasUpload }: { status: string | null; hasUpload: boolean }) {
  const steps = [
    { label: "Browser Upload", short: "UI", state: hasUpload ? "done" : "pending" },
    { label: "FastAPI API", short: "API", state: hasUpload ? "done" : "pending" },
    { label: "Redis Queue", short: "RQ", state: status === "QUEUED" ? "current" : ["PROCESSING", "COMPLETED", "FAILED"].includes(status || "") ? "done" : "pending" },
    { label: "FFmpeg Worker", short: "CPU", state: status === "PROCESSING" ? "current" : ["COMPLETED", "FAILED"].includes(status || "") ? "done" : "pending" },
    { label: "MinIO Storage", short: "S3", state: status === "COMPLETED" || status === "FAILED" ? "done" : "pending" },
    { label: "Presigned Assets", short: "URL", state: status === "COMPLETED" ? "current" : "pending" }
  ];

  return (
    <section className="rounded-[1.25rem] border border-white/10 bg-slate-900/80 p-4 shadow-xl shadow-black/20">
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white">Architecture Pipeline</h2>
          <p className="mt-1 text-sm text-slate-400">The active job state lights up the distributed path from browser to generated assets.</p>
        </div>
        <span className="rounded-full border border-blue-400/20 bg-blue-500/10 px-3 py-1 text-xs font-medium text-blue-200">AKS port-forward demo</span>
      </div>
      <ol className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {steps.map((step, index) => (
          <li key={step.label} className={`relative rounded-xl border p-3 ${pipelineClass(step.state)}`}>
            <div className="flex items-center justify-between gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-lg border border-current/15 bg-black/15 text-xs font-bold">{step.short}</span>
              <span className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{step.state}</span>
            </div>
            <div className="mt-2 text-sm font-semibold">{step.label}</div>
            {index < steps.length - 1 ? <div className="absolute -right-2 top-1/2 hidden h-px w-4 bg-white/15 xl:block" /> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function UploadPanel({
  file,
  idempotencyKey,
  uploading,
  uploadError,
  uploadHttpStatus,
  uploadLatencyMs,
  upload,
  onFileChange,
  onIdempotencyKeyChange,
  onSubmit
}: {
  file: File | null;
  idempotencyKey: string;
  uploading: boolean;
  uploadError: ApiFailure | null;
  uploadHttpStatus: number | null;
  uploadLatencyMs: number | null;
  upload: UploadResponse | null;
  onFileChange: (file: File | null) => void;
  onIdempotencyKeyChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const resultStatusCode = uploadHttpStatus || uploadError?.statusCode || null;
  const success = Boolean(resultStatusCode && resultStatusCode >= 200 && resultStatusCode < 300);

  return (
    <div className="space-y-5">
      <form onSubmit={onSubmit} className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-200">Video file</span>
          <input
            className="mt-2 block w-full rounded-xl border border-white/10 bg-slate-950/80 px-3 py-2 text-sm text-slate-300 shadow-sm file:mr-4 file:rounded-lg file:border-0 file:bg-blue-500 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white hover:border-white/20"
            type="file"
            accept="video/*,.mp4,.mov,.mkv,.webm"
            onChange={(event) => onFileChange(event.target.files?.[0] || null)}
          />
        </label>
        <div className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-400">
          Selected file: <span className="font-medium text-slate-100">{file?.name || "none"}</span>
        </div>
        <label className="block">
          <span className="text-sm font-medium text-slate-200">Idempotency-Key optional</span>
          <input
            className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none ring-blue-500/50 transition placeholder:text-slate-600 focus:border-blue-400/60 focus:ring-2"
            value={idempotencyKey}
            onChange={(event) => onIdempotencyKeyChange(event.target.value)}
            placeholder="demo-key-123"
          />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <button
            className="rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-950/30 transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:bg-slate-700"
            type="submit"
            disabled={uploading}
          >
            {uploading ? "Uploading..." : "Upload video"}
          </button>
          {uploadLatencyMs !== null ? <span className="text-sm text-slate-400">Latency {formatLatency(uploadLatencyMs)}</span> : null}
        </div>
        {uploadError ? (
          <Notice tone="error">
            <div className="font-medium">{uploadError.message}</div>
            <div className="mt-1 text-xs">
              Status code: {uploadError.statusCode || "not available"}
              {uploadError.reason ? ` | reason: ${uploadError.reason}` : null}
            </div>
          </Notice>
        ) : null}
      </form>

      {upload || uploadError?.statusCode ? (
        <div className="rounded-2xl border border-white/10 bg-slate-950/55 p-4 shadow-xl shadow-black/10">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-950">{httpStatusLabel(resultStatusCode)}</span>
              <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${success ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200" : "border-rose-400/40 bg-rose-500/15 text-rose-200"}`}>
                {uploadOutcomeLabel(resultStatusCode)}
              </span>
            </div>
            {upload?.status ? <StatusBadge status={upload.status} /> : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <DataTile label="ID" value={upload?.id} copyValue={upload?.id} mono />
            <DataTile label="Filename" value={upload?.original_filename} />
            <DataTile label="Queue job" value={upload?.queue_job_id} copyValue={upload?.queue_job_id} mono />
            <DataTile label="Storage backend" value={upload?.storage_backend} />
            <DataTile label="Idempotency key" value={upload?.idempotency_key} mono />
            <DataTile label="Attempts" value={upload ? `${upload.attempt_count} / ${upload.max_attempts}` : null} />
          </div>
          {uploadError ? (
            <div className="mt-4 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
              {uploadError.reason ? `Rejection reason: ${uploadError.reason}` : uploadError.message}
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyState title="No upload submitted" text="Choose a video and submit it to create or reuse a VideoJob." />
      )}
    </div>
  );
}

function JobStatusPanel({
  activeVideoId,
  currentStatus,
  pollingActive,
  status,
  statusError,
  upload
}: {
  activeVideoId: string | null;
  currentStatus: string;
  pollingActive: boolean;
  status: StatusResponse | null;
  statusError: string | null;
  upload: UploadResponse | null;
}) {
  return (
    <section className="rounded-[1.25rem] border border-white/10 bg-slate-900/80 p-5 shadow-xl shadow-black/20">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-200/70">Async worker state</p>
          <h2 className="mt-2 text-lg font-semibold text-white">Job Status</h2>
          <p className="mt-1 text-sm text-slate-400">Status polling follows the public job endpoint after upload.</p>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          <StatusBadge status={currentStatus} size="lg" />
          {pollingActive ? <span className="rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-200">Polling every 2 seconds</span> : null}
        </div>
      </div>
      {activeVideoId ? (
        <div className="mt-5 space-y-5">
          <StatusTimeline status={status?.status || upload?.status || null} hasUpload={Boolean(upload)} />
          {statusError ? <Notice tone="error">{statusError}</Notice> : null}
          <div className="grid gap-3 rounded-2xl border border-white/10 bg-black/20 p-4 sm:grid-cols-2 xl:grid-cols-4">
            <DataTile label="Video ID" value={activeVideoId} copyValue={activeVideoId} mono />
            <DataTile label="Attempts" value={status ? `${status.attempt_count} / ${status.max_attempts}` : "not available"} />
            <DataTile label="Processing duration" value={formatSeconds(status?.processing_duration_seconds)} />
            <DataTile label="Retry exhausted" value={status?.retry_exhausted ? "true" : "false"} />
          </div>
          {status?.error_message ? <Notice tone="error">{status.error_message}</Notice> : null}
        </div>
      ) : (
        <div className="mt-5">
          <EmptyState title="Waiting for a job" text="Upload a video to start status polling and watch the worker pipeline advance." />
        </div>
      )}
    </section>
  );
}

function AssetsPanel({ assets, assetsError, status }: { assets: AssetsResponse | null; assetsError: string | null; status: StatusResponse | null }) {
  return (
    <section className="rounded-[1.25rem] border border-white/10 bg-slate-900/80 p-5 shadow-xl shadow-black/20">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-200/70">Object storage output</p>
          <h2 className="mt-2 text-lg font-semibold text-white">Processed Assets</h2>
          <p className="mt-1 text-sm text-slate-400">Short-lived presigned URLs are generated after completion.</p>
        </div>
        <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">Short-lived presigned URLs</span>
      </div>
      {assetsError ? <div className="mt-4"><Notice tone="warning">{assetsError}</Notice></div> : null}
      {status?.status === "COMPLETED" ? (
        assets ? (
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <AssetPreviewCard title="Thumbnail" url={assets.thumbnail_url} copyLabel="Thumbnail URL">
              {assets.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="h-full max-h-80 w-full rounded-xl border border-white/10 bg-black object-contain" src={assets.thumbnail_url} alt="Generated thumbnail" />
              ) : (
                <EmptyAsset label="Thumbnail URL is unavailable" />
              )}
            </AssetPreviewCard>
            <AssetPreviewCard title="Processed video" url={assets.processed_url} copyLabel="Processed URL">
              {assets.processed_url ? (
                <video className="w-full rounded-xl border border-white/10 bg-black shadow-2xl shadow-black/30" src={assets.processed_url} controls />
              ) : (
                <EmptyAsset label="Processed video URL is unavailable" />
              )}
            </AssetPreviewCard>
          </div>
        ) : (
          <div className="mt-5">
            <EmptyState title="Loading asset URLs" text="The job is completed. Fetching presigned URLs from the assets endpoint." />
          </div>
        )
      ) : (
        <div className="mt-5">
          <EmptyState title="Assets pending" text="Processed video and thumbnail previews appear here after the job reaches COMPLETED." />
        </div>
      )}
    </section>
  );
}

function HealthSection({
  queueHealth,
  storageHealth,
  healthLoading,
  healthError,
  onRefresh
}: {
  queueHealth: QueueHealth | null;
  storageHealth: StorageHealth | null;
  healthLoading: boolean;
  healthError: string | null;
  onRefresh: () => void;
}) {
  const storageConnected = storageHealth?.connected ?? storageHealth?.healthy ?? null;
  const apiAvailable = queueHealth !== null || storageHealth !== null;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-400">Refresh these before a demo to prove API connectivity, Redis, worker visibility, and object storage.</p>
        <button
          className="rounded-xl border border-white/10 bg-white/[0.06] px-3 py-2 text-sm font-semibold text-slate-200 shadow-sm transition hover:border-white/20 hover:bg-white/[0.09] disabled:cursor-wait disabled:opacity-60"
          type="button"
          onClick={() => void onRefresh()}
          disabled={healthLoading}
        >
          {healthLoading ? "Refreshing..." : "Refresh"}
        </button>
      </div>
      {healthError ? <Notice tone="error">{healthError}</Notice> : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <HealthMetric title="API" value={apiAvailable ? "reachable" : "not available"} detail={API_BASE_URL} state={apiAvailable ? "ok" : "unknown"} />
        <HealthMetric title="Queue" value={queueHealth?.redis_connected ? "Redis connected" : "not available"} detail={queueHealth?.queue_name || "video-processing"} state={queueHealth?.redis_connected ? "ok" : "unknown"} />
        <HealthMetric title="Storage" value={storageConnected === null ? "not available" : storageConnected ? "MinIO reachable" : "storage error"} detail={storageHealth?.storage_backend || "object"} state={storageConnected ? "ok" : storageConnected === false ? "bad" : "unknown"} />
        <HealthMetric title="Worker Count" value={queueHealth?.worker_count ?? "not available"} detail={`pressure: ${queueHealth?.queue_pressure_level || "not available"}`} state={queueHealth && queueHealth.worker_count > 0 ? "ok" : "unknown"} />
      </div>
      <div className="grid gap-3 rounded-2xl border border-white/10 bg-black/20 p-4 sm:grid-cols-2">
        <DataTile label="Queued jobs" value={queueHealth?.queued_jobs_count} />
        <DataTile label="Storage endpoint" value={storageHealth?.public_endpoint || storageHealth?.endpoint} mono />
        <DataTile label="Expected buckets" value={storageHealth?.expected_buckets?.join(", ") || Object.keys(storageHealth?.buckets || {}).join(", ")} />
        <DataTile label="Errors" value={queueHealth?.redis_error || storageHealth?.error || "none reported"} />
      </div>
    </div>
  );
}

function AdminOperations({
  adminKey,
  adminLoading,
  retryingJobId,
  adminError,
  adminMessage,
  failedJobs,
  stuckJobs,
  recovery,
  onAdminKeyChange,
  onLoadFailedJobs,
  onLoadStuckJobs,
  onRecoverStuckJobs,
  onRetryJob
}: {
  adminKey: string;
  adminLoading: string | null;
  retryingJobId: string | null;
  adminError: string | null;
  adminMessage: string | null;
  failedJobs: FailedJob[];
  stuckJobs: StuckJob[];
  recovery: RecoveryResult | null;
  onAdminKeyChange: (value: string) => void;
  onLoadFailedJobs: () => void;
  onLoadStuckJobs: () => void;
  onRecoverStuckJobs: () => void;
  onRetryJob: (videoId: string) => void;
}) {
  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <label className="block">
          <span className="text-sm font-medium text-slate-200">Admin API key</span>
          <input
            className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none ring-blue-500/50 transition placeholder:text-slate-600 focus:border-blue-400/60 focus:ring-2"
            value={adminKey}
            onChange={(event) => onAdminKeyChange(event.target.value)}
            type="password"
            placeholder="dev-admin-key"
          />
          <span className="mt-2 block text-xs text-slate-500">Demo key stays in component state and is never persisted by the browser.</span>
        </label>
        <div className="flex flex-wrap gap-2">
          <AdminButton loading={adminLoading === "failed"} onClick={onLoadFailedJobs}>Load failed</AdminButton>
          <AdminButton loading={adminLoading === "stuck"} onClick={onLoadStuckJobs}>Load stuck</AdminButton>
          <AdminButton loading={adminLoading === "recover"} onClick={onRecoverStuckJobs}>Recover stuck</AdminButton>
        </div>
      </div>

      {adminError ? <Notice tone="error">{adminError}</Notice> : null}
      {adminMessage ? <Notice tone="success">{adminMessage}</Notice> : null}

      {recovery ? (
        <div className="grid gap-3 rounded-2xl border border-white/10 bg-black/20 p-4 sm:grid-cols-4">
          <DataTile label="Inspected" value={recovery.inspected_count} />
          <DataTile label="Recovered" value={recovery.recovered_count} />
          <DataTile label="Failed" value={recovery.failed_count} />
          <DataTile label="Skipped" value={recovery.skipped_count} />
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-2">
        <AdminList title="Failed jobs" count={failedJobs.length}>
          {failedJobs.length ? failedJobs.map((job) => (
            <div key={job.id} className="rounded-2xl border border-white/10 bg-slate-950/55 p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="break-all font-mono text-xs text-slate-500">{job.id}</div>
                  <div className="mt-2 text-sm font-semibold text-slate-100">{job.original_filename}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    <StatusBadge status={job.status} />
                    <span>{job.last_error_type || "unknown error"}</span>
                    <span>retry exhausted: {String(job.retry_exhausted)}</span>
                  </div>
                  <div className="mt-2 text-xs text-slate-500">{job.failed_at || "failed time unavailable"}</div>
                </div>
                <button
                  className="shrink-0 rounded-lg border border-white/10 bg-white/[0.06] px-3 py-1.5 text-xs font-semibold text-slate-200 shadow-sm transition hover:border-white/20 hover:bg-white/[0.1] disabled:cursor-wait disabled:opacity-60"
                  onClick={() => onRetryJob(job.id)}
                  disabled={retryingJobId === job.id}
                  type="button"
                >
                  {retryingJobId === job.id ? "Retrying" : "Retry"}
                </button>
              </div>
            </div>
          )) : <EmptyState title="No failed jobs loaded" text="Load failed jobs to inspect retry-exhausted or failed processing records." />}
        </AdminList>

        <AdminList title="Stuck jobs" count={stuckJobs.length}>
          {stuckJobs.length ? stuckJobs.map((job) => (
            <div key={job.id} className="rounded-2xl border border-white/10 bg-slate-950/55 p-4 shadow-sm">
              <div className="break-all font-mono text-xs text-slate-500">{job.id}</div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <StatusBadge status={job.status} />
                <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-200">{job.stuck_reason}</span>
              </div>
              <div className="mt-3 text-xs text-slate-500">age: {job.age_seconds.toFixed(0)}s</div>
            </div>
          )) : <EmptyState title="No stuck jobs loaded" text="Load stuck jobs to inspect reconciler recovery candidates." />}
        </AdminList>
      </div>
    </div>
  );
}

function StatusTimeline({ status, hasUpload }: { status: string | null; hasUpload: boolean }) {
  const finalLabel = status === "FAILED" ? "Failed" : "Completed";
  const steps = [
    { label: "Uploaded", state: hasUpload ? "done" : "pending" },
    { label: "Queued", state: status === "QUEUED" ? "current" : ["PROCESSING", "COMPLETED", "FAILED"].includes(status || "") ? "done" : "pending" },
    { label: "Processing", state: status === "PROCESSING" ? "current" : ["COMPLETED", "FAILED"].includes(status || "") ? "done" : "pending" },
    { label: finalLabel, state: status === "COMPLETED" || status === "FAILED" ? "current" : "pending" }
  ];

  return (
    <ol className="grid gap-3 sm:grid-cols-4">
      {steps.map((step, index) => (
        <li key={step.label} className={`relative rounded-2xl border p-4 ${timelineClass(step.state, step.label)}`}>
          <div className="flex items-center justify-between gap-3">
            <span className="grid h-7 w-7 place-items-center rounded-full border border-current/20 bg-black/15 text-xs font-bold">{index + 1}</span>
            <span className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{step.state === "current" ? "Current" : step.state === "done" ? "Done" : "Pending"}</span>
          </div>
          <div className="mt-3 text-sm font-semibold">{step.label}</div>
        </li>
      ))}
    </ol>
  );
}

function Panel({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: ReactNode }) {
  return (
    <section className="rounded-[1.25rem] border border-white/10 bg-slate-900/80 p-5 shadow-xl shadow-black/20">
      <div className="mb-5">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-200/70">{eyebrow}</p>
        <h2 className="mt-2 text-lg font-semibold text-white">{title}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-400">{description}</p>
      </div>
      {children}
    </section>
  );
}

function StatusBadge({ status, size = "sm" }: { status: string; size?: "sm" | "lg" }) {
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border font-semibold ${statusClass(status)} ${size === "lg" ? "px-3 py-1.5 text-sm" : "px-2.5 py-1 text-xs"}`}>
      <span className={`h-2 w-2 rounded-full ${statusDotClass(status)}`} />
      {status}
    </span>
  );
}

function DataTile({ label, value, copyValue, mono = false }: { label: string; value: ReactNode; copyValue?: string | null; mono?: boolean }) {
  return (
    <div className="min-w-0 rounded-xl border border-white/10 bg-slate-950/55 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
        {copyValue ? <CopyButton value={copyValue} compact /> : null}
      </div>
      <div className={`mt-2 break-words text-sm text-slate-100 ${mono ? "font-mono text-xs" : "font-medium"}`}>{valueOrFallback(value)}</div>
    </div>
  );
}

function HealthMetric({ title, value, detail, state }: { title: string; value: ReactNode; detail: ReactNode; state: "ok" | "bad" | "unknown" }) {
  const dot = state === "ok" ? "bg-emerald-500" : state === "bad" ? "bg-rose-500" : "bg-slate-300";
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/55 p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
        <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
      </div>
      <div className="mt-4 text-2xl font-semibold tracking-tight text-white">{valueOrFallback(value)}</div>
      <div className="mt-1 break-words text-xs text-slate-500">{valueOrFallback(detail)}</div>
    </div>
  );
}

function AssetPreviewCard({ title, url, copyLabel, children }: { title: string; url: string | null; copyLabel: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/55 p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">{url ? "URL available" : "Waiting for URL"}</p>
        </div>
        {url ? <CopyButton value={url}>{copyLabel}</CopyButton> : null}
      </div>
      <div className="grid min-h-52 place-items-center">{children}</div>
    </div>
  );
}

function EmptyAsset({ label }: { label: string }) {
  return <div className="grid h-52 w-full place-items-center rounded-xl border border-dashed border-white/15 bg-black/20 text-sm text-slate-500">{label}</div>;
}

function AdminButton({ children, loading, onClick }: { children: ReactNode; loading: boolean; onClick: () => void }) {
  return (
    <button
      className="rounded-xl bg-blue-500 px-3 py-2 text-xs font-semibold text-white shadow-lg shadow-blue-950/20 transition hover:bg-blue-400 disabled:cursor-wait disabled:bg-slate-700"
      onClick={onClick}
      disabled={loading}
      type="button"
    >
      {loading ? "Loading..." : children}
    </button>
  );
}

function AdminList({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
        <span className="rounded-full border border-white/10 bg-white/[0.06] px-2.5 py-1 text-xs font-semibold text-slate-300">{count}</span>
      </div>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/15 bg-black/20 p-4">
      <div className="text-sm font-semibold text-slate-200">{title}</div>
      <p className="mt-1 text-sm leading-6 text-slate-500">{text}</p>
    </div>
  );
}

function SystemLink({ label, href, description }: { label: string; href: string; description: string }) {
  return (
    <a className="rounded-2xl border border-white/10 bg-slate-950/55 p-4 text-sm font-semibold text-slate-100 transition hover:border-white/20 hover:bg-slate-900" href={href} target="_blank" rel="noreferrer">
      <span>{label}</span>
      <div className="mt-2 text-xs font-medium leading-5 text-slate-400">{description}</div>
      <div className="mt-2 break-all font-mono text-xs font-normal text-slate-500">{href}</div>
    </a>
  );
}

function RuntimeChip({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-1 text-slate-400 shadow-sm">
      <span className="font-semibold text-slate-200">{label}</span>
      <span className="ml-2 font-mono">{valueOrFallback(value)}</span>
    </div>
  );
}

function DarkMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-2 text-lg font-semibold text-white">{valueOrFallback(value)}</div>
    </div>
  );
}

function Notice({ children, tone }: { children: ReactNode; tone: "error" | "warning" | "success" }) {
  const classes = {
    error: "border-rose-400/35 bg-rose-500/10 text-rose-200",
    warning: "border-amber-400/35 bg-amber-500/10 text-amber-200",
    success: "border-emerald-400/35 bg-emerald-500/10 text-emerald-200"
  };
  return <div className={`rounded-xl border p-3 text-sm ${classes[tone]}`}>{children}</div>;
}

function ReliabilityCapabilities() {
  const capabilities = [
    "Idempotent uploads",
    "Retry-aware job tracking",
    "Stuck job recovery",
    "Cleanup policy controls",
    "Queue pressure/admission checks",
    "Object-storage health checks"
  ];

  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">Reliability Capabilities</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">Controls and guardrails built into the processing platform.</p>
        </div>
        <span className="rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-200">enabled</span>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {capabilities.map((capability) => (
          <div key={capability} className="flex items-center gap-2 rounded-xl border border-white/10 bg-slate-950/55 px-3 py-2 text-sm text-slate-300">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            <span>{capability}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function pipelineClass(state: string) {
  if (state === "current") return "border-blue-400/40 bg-blue-500/15 text-blue-100 shadow-lg shadow-blue-950/20";
  if (state === "done") return "border-emerald-400/35 bg-emerald-500/10 text-emerald-100";
  return "border-white/10 bg-slate-950/55 text-slate-500";
}

function timelineClass(state: string, label: string) {
  if (state === "current" && label === "Failed") return "border-rose-400/40 bg-rose-500/15 text-rose-100";
  if (state === "current") return "border-blue-400/40 bg-blue-500/15 text-blue-100 shadow-lg shadow-blue-950/20";
  if (state === "done") return "border-emerald-400/35 bg-emerald-500/10 text-emerald-100";
  return "border-white/10 bg-slate-950/55 text-slate-500";
}

function CopyButton({ value, compact = false, children }: { value: string; compact?: boolean; children?: ReactNode }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      className={`rounded-lg border border-white/10 bg-white/[0.06] font-semibold text-slate-200 shadow-sm transition hover:border-white/20 hover:bg-white/[0.1] ${compact ? "px-1.5 py-0.5 text-[10px]" : "px-2.5 py-1.5 text-xs"}`}
      type="button"
      onClick={copy}
    >
      {copied ? "Copied" : children || "Copy"}
    </button>
  );
}
