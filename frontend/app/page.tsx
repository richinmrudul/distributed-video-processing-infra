"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

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

async function readApiError(response: Response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.detail?.reason === "string") return body.detail.reason;
    if (typeof body?.detail?.message === "string") return body.detail.message;
    return JSON.stringify(body);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm text-slate-900">{value || "not available"}</div>
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
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [assetsError, setAssetsError] = useState<string | null>(null);

  const [adminKey, setAdminKey] = useState("");
  const [adminLoading, setAdminLoading] = useState<string | null>(null);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [failedJobs, setFailedJobs] = useState<FailedJob[]>([]);
  const [stuckJobs, setStuckJobs] = useState<StuckJob[]>([]);
  const [recovery, setRecovery] = useState<RecoveryResult | null>(null);

  const activeVideoId = status?.id || upload?.id || null;
  const terminal = status?.status === "COMPLETED" || status?.status === "FAILED";

  useEffect(() => {
    if (!upload?.id || terminal) return;
    let cancelled = false;

    async function loadStatus() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/videos/${upload?.id}/status`);
        if (!response.ok) throw new Error(await readApiError(response));
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
        if (!response.ok) throw new Error(await readApiError(response));
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

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setUploadError("Choose a video file first.");
      return;
    }

    setUploading(true);
    setUploadError(null);
    setStatus(null);
    setAssets(null);
    setStatusError(null);
    setAssetsError(null);

    const form = new FormData();
    form.append("file", file);
    const headers: HeadersInit = {};
    const key = idempotencyKey.trim();
    if (key) headers["Idempotency-Key"] = key;

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/videos/upload`, {
        method: "POST",
        headers,
        body: form
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const body = (await response.json()) as UploadResponse;
      setUpload(body);
      setStatus(body as StatusResponse);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function adminFetch<T>(path: string, options: RequestInit = {}) {
    if (!adminKey.trim()) throw new Error("Admin API key is required.");
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        ...(options.headers || {}),
        "X-Admin-API-Key": adminKey.trim()
      }
    });
    if (!response.ok) throw new Error(await readApiError(response));
    return (await response.json()) as T;
  }

  async function loadFailedJobs() {
    setAdminLoading("failed");
    setAdminError(null);
    try {
      const body = await adminFetch<{ jobs: FailedJob[] }>("/api/v1/jobs/failed");
      setFailedJobs(body.jobs);
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not load failed jobs");
    } finally {
      setAdminLoading(null);
    }
  }

  async function loadStuckJobs() {
    setAdminLoading("stuck");
    setAdminError(null);
    try {
      const body = await adminFetch<{ jobs: StuckJob[] }>("/api/v1/jobs/stuck");
      setStuckJobs(body.jobs);
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not load stuck jobs");
    } finally {
      setAdminLoading(null);
    }
  }

  async function recoverStuckJobs() {
    setAdminLoading("recover");
    setAdminError(null);
    try {
      const body = await adminFetch<RecoveryResult>("/api/v1/jobs/recover-stuck", { method: "POST" });
      setRecovery(body);
      await loadStuckJobs();
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not recover stuck jobs");
    } finally {
      setAdminLoading(null);
    }
  }

  async function retryJob(videoId: string) {
    setAdminLoading(videoId);
    setAdminError(null);
    try {
      await adminFetch<StatusResponse>(`/api/v1/jobs/${videoId}/retry`, { method: "POST" });
      await loadFailedJobs();
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : "Could not retry job");
    } finally {
      setAdminLoading(null);
    }
  }

  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-ink sm:text-3xl">Distributed Video Processing Console</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                A lightweight demo console for async upload, queueing, FFmpeg processing, object storage, recovery, and operator workflows.
              </p>
            </div>
            <div className="rounded-md bg-panel px-3 py-2 text-xs text-slate-600">
              API base URL: <span className="font-mono text-slate-900">{API_BASE_URL}</span>
            </div>
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
          <div className="space-y-6">
            <Section title="Upload">
              <form onSubmit={submitUpload} className="space-y-4">
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Video file</span>
                  <input
                    className="mt-2 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm file:mr-4 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white"
                    type="file"
                    accept="video/*,.mp4,.mov,.mkv,.webm"
                    onChange={(event) => setFile(event.target.files?.[0] || null)}
                  />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Idempotency-Key optional</span>
                  <input
                    className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none ring-sky-500 focus:ring-2"
                    value={idempotencyKey}
                    onChange={(event) => setIdempotencyKey(event.target.value)}
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
                {uploadError ? <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">{uploadError}</p> : null}
              </form>

              {upload ? (
                <div className="mt-5 grid gap-4 rounded-md bg-panel p-4 sm:grid-cols-2">
                  <Field label="ID" value={upload.id} />
                  <Field label="Status" value={<StatusPill status={upload.status} />} />
                  <Field label="Filename" value={upload.original_filename} />
                  <Field label="Queue job" value={upload.queue_job_id} />
                  <Field label="Storage" value={upload.storage_backend} />
                </div>
              ) : null}
            </Section>

            <Section title="Job Status">
              {activeVideoId ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <StatusPill status={currentStatus} />
                    {!terminal ? <span className="text-sm text-slate-500">Polling every 2 seconds</span> : null}
                  </div>
                  {statusError ? <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">{statusError}</p> : null}
                  <div className="grid gap-4 rounded-md bg-panel p-4 sm:grid-cols-2">
                    <Field label="Video ID" value={activeVideoId} />
                    <Field label="Attempts" value={status ? `${status.attempt_count} / ${status.max_attempts}` : "not available"} />
                    <Field label="Processing duration" value={formatSeconds(status?.processing_duration_seconds)} />
                    <Field label="Retry exhausted" value={status?.retry_exhausted ? "true" : "false"} />
                    {status?.error_message ? <Field label="Error" value={status.error_message} /> : null}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-slate-600">Upload a video to start polling job status.</p>
              )}
            </Section>

            <Section title="Assets">
              {assetsError ? <p className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">{assetsError}</p> : null}
              {status?.status === "COMPLETED" ? (
                assets ? (
                  <div className="space-y-4">
                    {assets.thumbnail_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img className="max-h-64 rounded-md border border-slate-200 object-contain" src={assets.thumbnail_url} alt="Generated thumbnail" />
                    ) : (
                      <p className="text-sm text-slate-600">Thumbnail URL is unavailable.</p>
                    )}
                    {assets.processed_url ? (
                      <video className="w-full rounded-md border border-slate-200" src={assets.processed_url} controls />
                    ) : (
                      <p className="text-sm text-slate-600">Processed video URL is unavailable.</p>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-slate-600">Loading asset URLs...</p>
                )
              ) : (
                <p className="text-sm text-slate-600">Assets are available after the job reaches COMPLETED.</p>
              )}
            </Section>
          </div>

          <div className="space-y-6">
            <Section title="Admin Operations">
              <div className="space-y-4">
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Admin API key</span>
                  <input
                    className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none ring-sky-500 focus:ring-2"
                    value={adminKey}
                    onChange={(event) => setAdminKey(event.target.value)}
                    type="password"
                    placeholder="dev-admin-key"
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <AdminButton loading={adminLoading === "failed"} onClick={loadFailedJobs}>Load failed jobs</AdminButton>
                  <AdminButton loading={adminLoading === "stuck"} onClick={loadStuckJobs}>Load stuck jobs</AdminButton>
                  <AdminButton loading={adminLoading === "recover"} onClick={recoverStuckJobs}>Recover stuck jobs</AdminButton>
                </div>
                {adminError ? <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">{adminError}</p> : null}
                {recovery ? (
                  <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">
                    Recovery inspected {recovery.inspected_count}, recovered {recovery.recovered_count}, failed {recovery.failed_count}, skipped {recovery.skipped_count}.
                  </p>
                ) : null}

                <AdminList title="Failed jobs">
                  {failedJobs.length ? failedJobs.map((job) => (
                    <div key={job.id} className="rounded-md border border-slate-200 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="break-all font-mono text-xs text-slate-600">{job.id}</div>
                          <div className="mt-1 text-sm font-medium text-slate-900">{job.original_filename}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            {job.last_error_type || "unknown error"} · retry exhausted: {String(job.retry_exhausted)}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">{job.failed_at || "failed time unavailable"}</div>
                        </div>
                        <button
                          className="shrink-0 rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-60"
                          onClick={() => retryJob(job.id)}
                          disabled={adminLoading === job.id}
                        >
                          {adminLoading === job.id ? "Retrying" : "Retry"}
                        </button>
                      </div>
                    </div>
                  )) : <EmptyState text="No failed jobs loaded." />}
                </AdminList>

                <AdminList title="Stuck jobs">
                  {stuckJobs.length ? stuckJobs.map((job) => (
                    <div key={job.id} className="rounded-md border border-slate-200 p-3">
                      <div className="break-all font-mono text-xs text-slate-600">{job.id}</div>
                      <div className="mt-2 flex items-center gap-2">
                        <StatusPill status={job.status} />
                        <span className="text-xs text-slate-500">{job.stuck_reason}</span>
                      </div>
                      <div className="mt-2 text-xs text-slate-500">age: {job.age_seconds.toFixed(0)}s</div>
                    </div>
                  )) : <EmptyState text="No stuck jobs loaded." />}
                </AdminList>
              </div>
            </Section>

            <Section title="System Links">
              <div className="grid gap-3 sm:grid-cols-2">
                <SystemLink label="API Docs" href="http://localhost:8000/docs" />
                <SystemLink label="Grafana" href="http://localhost:3000" />
                <SystemLink label="Prometheus" href="http://localhost:9090" />
                <SystemLink label="Jaeger" href="http://localhost:16686" />
                <SystemLink label="MinIO Console" href="http://localhost:9001" />
              </div>
              <p className="mt-4 text-xs text-slate-500">These links target the local Docker Compose development stack.</p>
            </Section>
          </div>
        </div>
      </div>
    </main>
  );
}

function StatusPill({ status }: { status: string }) {
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${statusClass(status)}`}>{status}</span>;
}

function AdminButton({ children, loading, onClick }: { children: React.ReactNode; loading: boolean; onClick: () => void }) {
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

function AdminList({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-800">{title}</h3>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="rounded-md border border-dashed border-slate-300 p-3 text-sm text-slate-500">{text}</p>;
}

function SystemLink({ label, href }: { label: string; href: string }) {
  return (
    <a className="rounded-md border border-slate-200 bg-panel p-3 text-sm font-medium text-slate-800 hover:border-slate-400" href={href} target="_blank" rel="noreferrer">
      {label}
      <div className="mt-1 break-all font-mono text-xs font-normal text-slate-500">{href}</div>
    </a>
  );
}
