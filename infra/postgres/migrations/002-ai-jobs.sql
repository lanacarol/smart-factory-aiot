-- Jobs de geracao de dados e treinamento da IA,
-- disparados pela interface e executados pelo worker ai-jobs.
CREATE TABLE IF NOT EXISTS public.ai_jobs (
    id uuid PRIMARY KEY,
    job_type character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    progress integer DEFAULT 0 NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    message character varying(500),
    log_tail text,
    result jsonb,
    requested_by character varying(80),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    CONSTRAINT chk_job_type CHECK (job_type IN ('generate', 'train')),
    CONSTRAINT chk_job_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed')
    ),
    CONSTRAINT chk_job_progress CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_ai_jobs_created_at
    ON public.ai_jobs (created_at DESC);
