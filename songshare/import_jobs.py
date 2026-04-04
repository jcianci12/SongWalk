from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class ImportJob:
    id: str
    library_id: str
    source: str
    source_url: str
    state: str = "queued"
    message: str = "Queued"
    progress_percent: int | None = None
    logs: list[str] = field(default_factory=list)
    uploaded: int = 0
    redirect_url: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "library_id": self.library_id,
            "source": self.source,
            "source_url": self.source_url,
            "state": self.state,
            "message": self.message,
            "progress_percent": self.progress_percent,
            "logs": list(self.logs),
            "uploaded": self.uploaded,
            "redirect_url": self.redirect_url,
            "error": self.error,
        }


class ImportJobManager:
    def __init__(self, *, retention_seconds: int = 3600, max_logs: int = 12):
        self._retention_seconds = retention_seconds
        self._max_logs = max_logs
        self._jobs: dict[str, ImportJob] = {}
        self._lock = threading.Lock()

    def create_job(
        self,
        *,
        library_id: str,
        source: str,
        source_url: str,
        redirect_url: str,
        worker,
    ) -> ImportJob:
        job = ImportJob(
            id=str(uuid4()),
            library_id=library_id,
            source=source,
            source_url=source_url,
            message=f"Queued {source} import...",
            progress_percent=0,
        )
        with self._lock:
            self._prune_locked()
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job.id, redirect_url, worker),
            name=f"songshare-import-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return job

    def get_job(self, job_id: str) -> ImportJob | None:
        with self._lock:
            self._prune_locked()
            job = self._jobs.get(job_id)
            if not job:
                return None
            return ImportJob(**job.to_dict(), created_at=job.created_at, updated_at=job.updated_at)

    def update_job(
        self,
        job_id: str,
        *,
        state: str | None = None,
        message: str | None = None,
        progress_percent: int | None = None,
        detail: str | None = None,
        uploaded: int | None = None,
        redirect_url: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return

            if state is not None:
                job.state = state
            if message is not None:
                job.message = message
            if progress_percent is not None:
                job.progress_percent = max(0, min(100, int(progress_percent)))
            if detail:
                job.logs.append(detail)
                job.logs = job.logs[-self._max_logs :]
            if uploaded is not None:
                job.uploaded = uploaded
            if redirect_url is not None:
                job.redirect_url = redirect_url
            if error is not None:
                job.error = error
            job.updated_at = time.time()

    def _run_job(self, job_id: str, redirect_url: str, worker) -> None:
        self.update_job(job_id, state="running", message="Starting import...", progress_percent=2)

        def progress(message: str, *, progress_percent: int | None = None, detail: str = "") -> None:
            self.update_job(
                job_id,
                state="running",
                message=message,
                progress_percent=progress_percent,
                detail=detail,
            )

        try:
            outcome = worker(progress)
        except Exception as exc:
            self.update_job(
                job_id,
                state="failed",
                message=str(exc),
                error=str(exc),
                progress_percent=100,
            )
            return

        if not getattr(outcome, "ok", False):
            message = (getattr(outcome, "errors", None) or ["Import failed."])[0]
            self.update_job(
                job_id,
                state="failed",
                message=message,
                error=message,
                uploaded=getattr(outcome, "uploaded", 0),
                progress_percent=100,
            )
            return

        self.update_job(
            job_id,
            state="completed",
            message=f"Imported {getattr(outcome, 'uploaded', 0)} track{'s' if getattr(outcome, 'uploaded', 0) != 1 else ''}.",
            uploaded=getattr(outcome, "uploaded", 0),
            redirect_url=redirect_url,
            progress_percent=100,
        )

    def _prune_locked(self) -> None:
        cutoff = time.time() - self._retention_seconds
        stale_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.updated_at < cutoff and job.state in {"completed", "failed"}
        ]
        for job_id in stale_job_ids:
            self._jobs.pop(job_id, None)
