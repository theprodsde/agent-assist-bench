-- storage/schema.sql
-- SQLite schema for AgentAssistBench

-- The MVP schema is intentionally additive and initialization-safe: the storage
-- manager uses IF NOT EXISTS throughout, so reopening an existing database does
-- not recreate or discard persisted rows. JSON payload evolution is handled by
-- benchmark.storage.codec without requiring destructive schema migrations.

CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    source TEXT NOT NULL CHECK(source IN ('telegram', 'discord', 'cli', 'api')),
    prompt TEXT NOT NULL,
    attachments_json TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'running', 'completed', 'partially_failed', 'failed')),
    tags_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    execution_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    benchmark_id TEXT NOT NULL REFERENCES benchmarks(id),
    agent_name TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    deployment_provider TEXT NOT NULL,
    deployment_type TEXT NOT NULL
        CHECK(deployment_type IN ('local_docker', 'vm', 'managed_container')),
    cpu_cores REAL,
    memory_mb INTEGER,
    cold_start_ms REAL,
    total_latency_ms REAL NOT NULL,
    network_latency_ms REAL,
    llm_model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    api_latency_ms REAL,
    estimated_cost_usd REAL,
    estimated_infra_cost_usd REAL,
    raw_response TEXT NOT NULL,
    tool_calls_json TEXT,
    browser_actions_json TEXT,
    errors_json TEXT DEFAULT '[]',
    logs_json TEXT DEFAULT '[]',
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    benchmark_id TEXT NOT NULL UNIQUE REFERENCES benchmarks(id),
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    preferred_agent TEXT,
    preferred_deployment TEXT,
    notes TEXT,
    evaluator TEXT,
    evaluated_at TEXT NOT NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_benchmarks_status ON benchmarks(status);
CREATE INDEX IF NOT EXISTS idx_benchmarks_created_at ON benchmarks(created_at);
CREATE INDEX IF NOT EXISTS idx_benchmarks_source ON benchmarks(source);
CREATE INDEX IF NOT EXISTS idx_executions_benchmark_id ON executions(benchmark_id);
CREATE INDEX IF NOT EXISTS idx_executions_agent ON executions(agent_name, deployment_type);
CREATE INDEX IF NOT EXISTS idx_evaluations_benchmark_id ON evaluations(benchmark_id);
