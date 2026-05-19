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
  QUEUED: "bg-slate-100 text-slate-700 ring-slate-200",
  PROCESSING: "bg-sky-100 text-sky-700 ring-sky-200",
  COMPLETED: "bg-emerald-100 text-emerald-700 ring-emerald-200",
  FAILED: "bg-rose-100 text-rose-700 ring-rose-200"
};

function statusClass(status: string) {
  return statusStyles[status] || "bg-zinc-100 text-zinc-700 ring-zinc-200";
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

function Section({ title, eyebrow, children }: { title: string; eyebrow?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      {eyebrow ? <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{eyebrow}</div> : null}
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Field({ label, value, copyValue }: { label: string; value: ReactNode; copyValue?: string | null }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
        {copyValue ? <CopyButton value={copyValue} compact /> : null}
      </div>
      <div className="mt-1 break-words text-sm text-slate-900">{valueOrFallback(value)}</div>
    </div>
  );
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
    if (!adminKey.trim()) throw new Error("Enter the local dev admin key before calling operator endpoints.");
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
    <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Demo console</p>
              <h1 className="mt-1 text-2xl font-semibold text-ink sm:text-3xl">Distributed Video Processing Console</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                Upload a video, watch it move through the async queue and FFmpeg workers, then use operator controls to inspect recovery paths.
                Observability stays in Grafana, Prometheus, and Jaeger.
              </p>
            </div>
            <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-2 lg:min-w-96">
              <InfoBadge label="API" value={API_BASE_URL} />
              <InfoBadge label="Processing" value="Redis/RQ workers" />
              <InfoBadge label="Storage" value="Object storage" />
              <InfoBadge label="Admin" value="X-Admin-API-Key" />
            </div>
          </div>
        </header>

        <Section title="Public workflow" eyebrow="Client path">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
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
            <div className="space-y-5">
              <JobStatusPanel
                activeVideoId={activeVideoId}
                currentStatus={currentStatus}
                terminal={terminal}
                status={status}
                statusError={statusError}
                upload={upload}
              />
              <AssetsPanel assets={assets} assetsError={assetsError} status={status} />
            </div>
          </div>
        </Section>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <Section title="System Health" eyebrow="Public infrastructure checks">
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-600">Queue and storage health endpoints are public checks for local demo readiness.</p>
              <button
                className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60"
                type="button"
                onClick={() => void loadHealth()}
                disabled={healthLoading}
              >
                {healthLoading ? "Refreshing..." : "Refresh"}
              </button>
            </div>
            {healthError ? <Notice tone="error">{healthError}</Notice> : null}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
              <HealthCard title="Queue">
                <Field label="Redis connected" value={queueHealth ? String(queueHealth.redis_connected) : null} />
                <Field label="Queue name" value={queueHealth?.queue_name} />
                <Field label="Queued jobs" value={queueHealth?.queued_jobs_count} />
                <Field label="Workers" value={queueHealth?.worker_count} />
                <Field label="Pressure" value={queueHealth?.queue_pressure_level} />
                {queueHealth?.redis_error ? <Field label="Redis error" value={queueHealth.redis_error} /> : null}
              </HealthCard>
              <HealthCard title="Storage">
                <Field label="Connected" value={storageHealth?.connected !== undefined ? String(storageHealth.connected) : storageHealth?.healthy !== undefined ? String(storageHealth.healthy) : null} />
                <Field label="Status" value={storageHealth?.status || (storageHealth?.connected ? "connected" : storageHealth?.error ? "error" : null)} />
                <Field label="Backend" value={storageHealth?.storage_backend} />
                <Field label="Endpoint" value={storageHealth?.public_endpoint || storageHealth?.endpoint} />
                <Field label="Buckets" value={storageHealth?.expected_buckets?.join(", ") || Object.keys(storageHealth?.buckets || {}).join(", ")} />
                {storageHealth?.error ? <Field label="Storage error" value={storageHealth.error} /> : null}
              </HealthCard>
            </div>
          </Section>

          <Section title="Operator workflow" eyebrow="Protected admin path">
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
          </Section>
        </div>

        <Section title="Observability" eyebrow="Local stack">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <DemoScenarios />
            <div>
              <div className="grid gap-3 sm:grid-cols-2">
                <SystemLink label="API Docs" href="http://localhost:8000/docs" />
                <SystemLink label="Grafana" href="http://localhost:3000" />
                <SystemLink label="Prometheus" href="http://localhost:9090" />
                <SystemLink label="Jaeger" href="http://localhost:16686" />
                <SystemLink label="MinIO Console" href="http://localhost:9001" />
              </div>
              <p className="mt-4 text-xs text-slate-500">These links target the local Docker Compose development stack.</p>
            </div>
          </div>
        </Section>
      </div>
    </main>
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
  return (
    <div className="rounded-lg border border-slate-200 bg-panel p-4">
      <h3 className="text-sm font-semibold text-slate-900">Upload video</h3>
      <p className="mt-1 text-sm text-slate-600">New uploads return 201. Reused idempotency keys return the existing job with 200.</p>
      <form onSubmit={onSubmit} className="mt-4 space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Video file</span>
          <input
            className="mt-2 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm file:mr-4 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white"
            type="file"
            accept="video/*,.mp4,.mov,.mkv,.webm"
            onChange={(event) => onFileChange(event.target.files?.[0] || null)}
          />
        </label>
        <div className="rounded-md bg-white px-3 py-2 text-sm text-slate-700">
          Selected file: <span className="font-medium text-slate-950">{file?.name || "none"}</span>
        </div>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Idempotency-Key optional</span>
          <input
            className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none ring-sky-500 focus:ring-2"
            value={idempotencyKey}
            onChange={(event) => onIdempotencyKeyChange(event.target.value)}
            placeholder="demo-key-123"
          />
        </label>
        <button
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-slate-400"
          type="submit"
          disabled={uploading}
        >
          {uploading ? "Uploading..." : "Upload video"}
        </button>
        {uploadLatencyMs !== null ? <p className="text-sm text-slate-600">Upload latency: {formatLatency(uploadLatencyMs)}</p> : null}
        {uploadError ? (
          <Notice tone="error">
            <div className="font-medium">{uploadError.message}</div>
            <div className="mt-1 text-xs">
              Status code: {uploadError.statusCode || "not available"}
              {uploadError.reason ? ` · reason: ${uploadError.reason}` : null}
            </div>
          </Notice>
        ) : null}
      </form>

      {upload || uploadError?.statusCode ? (
        <div className="mt-5 rounded-md bg-white p-4">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white">{httpStatusLabel(uploadHttpStatus || uploadError?.statusCode || null)}</span>
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${uploadHttpStatus && uploadHttpStatus >= 200 && uploadHttpStatus < 300 ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-rose-50 text-rose-700 ring-rose-200"}`}>
              {uploadOutcomeLabel(uploadHttpStatus || uploadError?.statusCode || null)}
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="ID" value={upload?.id} copyValue={upload?.id} />
            <Field label="Job status" value={upload ? <StatusPill status={upload.status} /> : "not available"} />
            <Field label="Filename" value={upload?.original_filename} />
            <Field label="Queue job" value={upload?.queue_job_id} copyValue={upload?.queue_job_id} />
            <Field label="Storage" value={upload?.storage_backend} />
            <Field label="Idempotency key" value={upload?.idempotency_key} />
          </div>
          {uploadError ? (
            <div className="mt-4 text-sm text-rose-700">
              {uploadError.reason ? `Rejection reason: ${uploadError.reason}` : uploadError.message}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function JobStatusPanel({
  activeVideoId,
  currentStatus,
  terminal,
  status,
  statusError,
  upload
}: {
  activeVideoId: string | null;
  currentStatus: string;
  terminal: boolean;
  status: StatusResponse | null;
  statusError: string | null;
  upload: UploadResponse | null;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-panel p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Job status</h3>
          <p className="mt-1 text-sm text-slate-600">The browser polls the public status endpoint every 2 seconds after upload.</p>
        </div>
        <StatusPill status={currentStatus} />
      </div>
      {activeVideoId ? (
        <div className="mt-4 space-y-4">
          <StatusTimeline status={status?.status || upload?.status || null} hasUpload={Boolean(upload)} />
          {!terminal ? <span className="text-sm text-slate-500">Polling every 2 seconds</span> : null}
          {statusError ? <Notice tone="error">{statusError}</Notice> : null}
          <div className="grid gap-4 rounded-md bg-white p-4 sm:grid-cols-2">
            <Field label="Video ID" value={activeVideoId} copyValue={activeVideoId} />
            <Field label="Attempts" value={status ? `${status.attempt_count} / ${status.max_attempts}` : "not available"} />
            <Field label="Processing duration" value={formatSeconds(status?.processing_duration_seconds)} />
            <Field label="Retry exhausted" value={status?.retry_exhausted ? "true" : "false"} />
            {status?.error_message ? <Field label="Error" value={status.error_message} /> : null}
          </div>
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-600">Upload a video to start polling job status.</p>
      )}
    </div>
  );
}

function AssetsPanel({ assets, assetsError, status }: { assets: AssetsResponse | null; assetsError: string | null; status: StatusResponse | null }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-panel p-4">
      <h3 className="text-sm font-semibold text-slate-900">Processed assets</h3>
      <p className="mt-1 text-sm text-slate-600">Completed object-storage jobs expose short-lived presigned URLs.</p>
      {assetsError ? <div className="mt-4"><Notice tone="warning">{assetsError}</Notice></div> : null}
      {status?.status === "COMPLETED" ? (
        assets ? (
          <div className="mt-4 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Processed URL" value={assets.processed_url ? "available" : null} copyValue={assets.processed_url} />
              <Field label="Thumbnail URL" value={assets.thumbnail_url ? "available" : null} copyValue={assets.thumbnail_url} />
            </div>
            {assets.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img className="max-h-64 rounded-md border border-slate-200 bg-white object-contain" src={assets.thumbnail_url} alt="Generated thumbnail" />
            ) : (
              <p className="text-sm text-slate-600">Thumbnail URL is unavailable.</p>
            )}
            {assets.processed_url ? (
              <video className="w-full rounded-md border border-slate-200 bg-black" src={assets.processed_url} controls />
            ) : (
              <p className="text-sm text-slate-600">Processed video URL is unavailable.</p>
            )}
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-600">Loading asset URLs...</p>
        )
      ) : (
        <p className="mt-4 text-sm text-slate-600">Assets are available after the job reaches COMPLETED.</p>
      )}
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
    <div className="space-y-4">
      <label className="block">
        <span className="text-sm font-medium text-slate-700">Admin API key</span>
        <input
          className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none ring-sky-500 focus:ring-2"
          value={adminKey}
          onChange={(event) => onAdminKeyChange(event.target.value)}
          type="password"
          placeholder="dev-admin-key"
        />
        <span className="mt-2 block text-xs text-slate-500">Local Docker Compose dev key only. The key stays in component state and is not persisted.</span>
      </label>
      <div className="flex flex-wrap gap-2">
        <AdminButton loading={adminLoading === "failed"} onClick={onLoadFailedJobs}>Load failed jobs</AdminButton>
        <AdminButton loading={adminLoading === "stuck"} onClick={onLoadStuckJobs}>Load stuck jobs</AdminButton>
        <AdminButton loading={adminLoading === "recover"} onClick={onRecoverStuckJobs}>Recover stuck jobs</AdminButton>
      </div>
      {adminError ? <Notice tone="error">{adminError}</Notice> : null}
      {adminMessage ? <Notice tone="success">{adminMessage}</Notice> : null}
      {recovery ? (
        <div className="grid gap-3 rounded-md bg-slate-50 p-3 text-sm text-slate-700 sm:grid-cols-4">
          <Field label="Inspected" value={recovery.inspected_count} />
          <Field label="Recovered" value={recovery.recovered_count} />
          <Field label="Failed" value={recovery.failed_count} />
          <Field label="Skipped" value={recovery.skipped_count} />
        </div>
      ) : null}

      <AdminList title="Failed jobs">
        {failedJobs.length ? failedJobs.map((job) => (
          <div key={job.id} className="rounded-md border border-slate-200 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="break-all font-mono text-xs text-slate-600">{job.id}</div>
                <div className="mt-1 text-sm font-medium text-slate-900">{job.original_filename}</div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <StatusPill status={job.status} />
                  <span>{job.last_error_type || "unknown error"}</span>
                  <span>retry exhausted: {String(job.retry_exhausted)}</span>
                </div>
                <div className="mt-1 text-xs text-slate-500">{job.failed_at || "failed time unavailable"}</div>
              </div>
              <button
                className="shrink-0 rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:cursor-wait disabled:opacity-60"
                onClick={() => onRetryJob(job.id)}
                disabled={retryingJobId === job.id}
                type="button"
              >
                {retryingJobId === job.id ? "Retrying" : "Retry"}
              </button>
            </div>
          </div>
        )) : <EmptyState text="No failed jobs loaded. Use the button above to query the admin endpoint." />}
      </AdminList>

      <AdminList title="Stuck jobs">
        {stuckJobs.length ? stuckJobs.map((job) => (
          <div key={job.id} className="rounded-md border border-slate-200 p-3">
            <div className="break-all font-mono text-xs text-slate-600">{job.id}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusPill status={job.status} />
              <span className="text-xs text-slate-500">{job.stuck_reason}</span>
            </div>
            <div className="mt-2 text-xs text-slate-500">age: {job.age_seconds.toFixed(0)}s</div>
          </div>
        )) : <EmptyState text="No stuck jobs loaded. Use the button above to inspect reconciler candidates." />}
      </AdminList>
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
    <ol className="grid gap-2 sm:grid-cols-4">
      {steps.map((step) => (
        <li key={step.label} className={`rounded-md border p-3 ${timelineClass(step.state, step.label)}`}>
          <div className="text-xs font-semibold uppercase tracking-wide">{step.state === "current" ? "Current" : step.state === "done" ? "Done" : "Pending"}</div>
          <div className="mt-1 text-sm font-medium">{step.label}</div>
        </li>
      ))}
    </ol>
  );
}

function timelineClass(state: string, label: string) {
  if (state === "current" && label === "Failed") return "border-rose-200 bg-rose-50 text-rose-800";
  if (state === "current") return "border-sky-200 bg-sky-50 text-sky-800";
  if (state === "done") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  return "border-slate-200 bg-white text-slate-500";
}

function StatusPill({ status }: { status: string }) {
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${statusClass(status)}`}>{status}</span>;
}

function AdminButton({ children, loading, onClick }: { children: ReactNode; loading: boolean; onClick: () => void }) {
  return (
    <button
      className="rounded-md bg-slate-900 px-3 py-2 text-xs font-medium text-white disabled:cursor-wait disabled:bg-slate-400"
      onClick={onClick}
      disabled={loading}
      type="button"
    >
      {loading ? "Loading..." : children}
    </button>
  );
}

function AdminList({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-800">{title}</h3>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="rounded-md border border-dashed border-slate-300 bg-white p-3 text-sm text-slate-500">{text}</p>;
}

function SystemLink({ label, href }: { label: string; href: string }) {
  return (
    <a className="rounded-md border border-slate-200 bg-panel p-3 text-sm font-medium text-slate-800 hover:border-slate-400" href={href} target="_blank" rel="noreferrer">
      {label}
      <div className="mt-1 break-all font-mono text-xs font-normal text-slate-500">{href}</div>
    </a>
  );
}

function InfoBadge({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-panel px-3 py-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-all font-mono text-xs text-slate-900">{value}</div>
    </div>
  );
}

function Notice({ children, tone }: { children: ReactNode; tone: "error" | "warning" | "success" }) {
  const classes = {
    error: "bg-rose-50 text-rose-700",
    warning: "bg-amber-50 text-amber-800",
    success: "bg-emerald-50 text-emerald-800"
  };
  return <div className={`rounded-md p-3 text-sm ${classes[tone]}`}>{children}</div>;
}

function HealthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-panel p-4">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <div className="grid gap-3">{children}</div>
    </div>
  );
}

function DemoScenarios() {
  return (
    <div className="rounded-lg border border-slate-200 bg-panel p-4">
      <h3 className="text-sm font-semibold text-slate-900">Demo scenarios</h3>
      <ol className="mt-3 space-y-3 text-sm text-slate-700">
        <li><span className="font-medium text-slate-950">Normal flow:</span> upload a valid MP4, watch status reach COMPLETED, then preview assets.</li>
        <li><span className="font-medium text-slate-950">Failure flow:</span> upload a fake bad.mp4 from the terminal, load failed jobs, then retry.</li>
        <li><span className="font-medium text-slate-950">Protection flow:</span> run the overload benchmark and observe rate limiting or admission rejection.</li>
        <li><span className="font-medium text-slate-950">Observability:</span> open Grafana or Jaeger after an upload to inspect metrics and traces.</li>
      </ol>
    </div>
  );
}

function CopyButton({ value, compact = false }: { value: string; compact?: boolean }) {
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
      className={`rounded-md border border-slate-300 bg-white font-medium text-slate-700 hover:bg-slate-50 ${compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-xs"}`}
      type="button"
      onClick={copy}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
