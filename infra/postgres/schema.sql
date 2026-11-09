--
-- PostgreSQL database dump
--

\restrict IdBgRsspW7WLkVGQ6709KcZE7RpcC5mobe29ZKbD46A8qCvkw8pKbyYO5G2Rerw

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id bigint NOT NULL,
    user_id integer,
    action character varying(100) NOT NULL,
    entity_type character varying(100) NOT NULL,
    entity_id character varying(100),
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: command_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.command_history (
    id bigint NOT NULL,
    event_id uuid NOT NULL,
    device_id character varying(100) NOT NULL,
    action character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'queued'::character varying NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    executed_at timestamp with time zone,
    error_message text,
    CONSTRAINT chk_command_action CHECK (((action)::text = ANY ((ARRAY['ON'::character varying, 'OFF'::character varying, 'INJECT_FAULT'::character varying, 'MAINTENANCE'::character varying])::text[]))),
    CONSTRAINT chk_command_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'executed'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: command_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.command_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: command_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.command_history_id_seq OWNED BY public.command_history.id;


--
-- Name: devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.devices (
    id integer NOT NULL,
    device_id character varying(100) NOT NULL,
    name character varying(150) NOT NULL,
    device_type character varying(50) NOT NULL,
    location character varying(150),
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: devices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.devices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: devices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.devices_id_seq OWNED BY public.devices.id;


--
-- Name: maintenance_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_alerts (
    id bigint NOT NULL,
    device_id character varying(100) NOT NULL,
    severity character varying(20) NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    health_percent double precision,
    rul_cycles double precision,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    CONSTRAINT chk_alert_severity CHECK (((severity)::text = ANY ((ARRAY['info'::character varying, 'warning'::character varying, 'critical'::character varying])::text[]))),
    CONSTRAINT chk_alert_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'acknowledged'::character varying, 'resolved'::character varying])::text[]))),
    CONSTRAINT chk_health_range CHECK (((health_percent IS NULL) OR ((health_percent >= (0)::double precision) AND (health_percent <= (100)::double precision)))),
    CONSTRAINT chk_rul_range CHECK (((rul_cycles IS NULL) OR (rul_cycles >= (0)::double precision)))
);


--
-- Name: maintenance_alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.maintenance_alerts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: maintenance_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.maintenance_alerts_id_seq OWNED BY public.maintenance_alerts.id;


--
-- Name: monitoring_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.monitoring_rules (
    id integer NOT NULL,
    device_id character varying(100) NOT NULL,
    rule_name character varying(150) NOT NULL,
    metric character varying(100) NOT NULL,
    operator character varying(10) NOT NULL,
    threshold double precision NOT NULL,
    severity character varying(20) DEFAULT 'warning'::character varying NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_rule_operator CHECK (((operator)::text = ANY ((ARRAY['>'::character varying, '>='::character varying, '<'::character varying, '<='::character varying, '='::character varying])::text[]))),
    CONSTRAINT chk_rule_severity CHECK (((severity)::text = ANY ((ARRAY['info'::character varying, 'warning'::character varying, 'critical'::character varying])::text[])))
);


--
-- Name: monitoring_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.monitoring_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: monitoring_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.monitoring_rules_id_seq OWNED BY public.monitoring_rules.id;


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: command_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history ALTER COLUMN id SET DEFAULT nextval('public.command_history_id_seq'::regclass);


--
-- Name: devices id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices ALTER COLUMN id SET DEFAULT nextval('public.devices_id_seq'::regclass);


--
-- Name: maintenance_alerts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_alerts ALTER COLUMN id SET DEFAULT nextval('public.maintenance_alerts_id_seq'::regclass);


--
-- Name: monitoring_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rules ALTER COLUMN id SET DEFAULT nextval('public.monitoring_rules_id_seq'::regclass);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: command_history command_history_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history
    ADD CONSTRAINT command_history_event_id_key UNIQUE (event_id);


--
-- Name: command_history command_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history
    ADD CONSTRAINT command_history_pkey PRIMARY KEY (id);


--
-- Name: devices devices_device_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_device_id_key UNIQUE (device_id);


--
-- Name: devices devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devices
    ADD CONSTRAINT devices_pkey PRIMARY KEY (id);


--
-- Name: maintenance_alerts maintenance_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_alerts
    ADD CONSTRAINT maintenance_alerts_pkey PRIMARY KEY (id);


--
-- Name: monitoring_rules monitoring_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rules
    ADD CONSTRAINT monitoring_rules_pkey PRIMARY KEY (id);


--
-- Name: idx_alerts_detected_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_detected_at ON public.maintenance_alerts USING btree (detected_at DESC);


--
-- Name: idx_alerts_device; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_device ON public.maintenance_alerts USING btree (device_id);


--
-- Name: idx_alerts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_status ON public.maintenance_alerts USING btree (status);


--
-- Name: idx_audit_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_created_at ON public.audit_logs USING btree (created_at DESC);


--
-- Name: idx_audit_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_entity ON public.audit_logs USING btree (entity_type, entity_id);


--
-- Name: idx_commands_device; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commands_device ON public.command_history USING btree (device_id);


--
-- Name: idx_commands_requested_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commands_requested_at ON public.command_history USING btree (requested_at DESC);


--
-- Name: maintenance_alerts fk_alert_device; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_alerts
    ADD CONSTRAINT fk_alert_device FOREIGN KEY (device_id) REFERENCES public.devices(device_id);


--
-- Name: command_history fk_command_device; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.command_history
    ADD CONSTRAINT fk_command_device FOREIGN KEY (device_id) REFERENCES public.devices(device_id);


--
-- Name: monitoring_rules fk_monitoring_device; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rules
    ADD CONSTRAINT fk_monitoring_device FOREIGN KEY (device_id) REFERENCES public.devices(device_id);


--
-- PostgreSQL database dump complete
--

\unrestrict IdBgRsspW7WLkVGQ6709KcZE7RpcC5mobe29ZKbD46A8qCvkw8pKbyYO5G2Rerw

-- Jobs de IA (ver infra/postgres/migrations/002-ai-jobs.sql)
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
