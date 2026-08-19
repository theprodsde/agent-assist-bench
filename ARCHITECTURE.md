# AgentAssistBench Architecture

## System Overview

AgentAssistBench is a modular evaluation framework that isolates three independent concerns:

```mermaid
graph TB
    User["👤 User / Operator"]
    
    subgraph CLI["CLI Layer"]
        Run["aab run<br/>(Submit prompt)"]
        Status["aab status<br/>(Check progress)"]
        Evaluate["aab evaluate<br/>(Rate responses)"]
        Report["aab report<br/>(View results)"]
    end
    
    subgraph Core["Core System"]
        Runner["BenchmarkRunner<br/>(Orchestration)"]
        Registry["AgentRegistry<br/>(Registration)"]
        Storage["StorageManager<br/>(Persistence)"]
        EvalService["EvaluationService<br/>(Validation)"]
    end
    
    subgraph Agents["Agent Adapters"]
        OAI["OpenAI-Compatible<br/>(HTTP contract)"]
        Hermes["Hermes Adapter<br/>(Agent-specific)"]
        OpenClaw["OpenClaw Adapter<br/>(Agent-specific)"]
    end
    
    subgraph Deployment["Deployment Targets"]
        LocalDocker["Local Docker<br/>:8001 / :8002"]
        VM["Virtual Machine<br/>SSH + HTTP"]
        ManagedContainer["Managed Container<br/>ACA / Cloud Run"]
    end
    
    subgraph Database["Persistence"]
        SQLite["SQLite Database<br/>(benchmarks, executions, evaluations)"]
        Exports["JSONL + CSV<br/>(Daily snapshots)"]
    end
    
    User --> CLI
    CLI --> Runner
    CLI --> Storage
    CLI --> EvalService
    
    Runner --> Registry
    Registry --> OAI
    OAI --> Hermes
    OAI --> OpenClaw
    
    Hermes --> Deployment
    OpenClaw --> Deployment
    
    Runner --> Storage
    Storage --> SQLite
    Storage --> Exports

    style User fill:#e1f5fe
    style Runner fill:#e8f5e9
    style SQLite fill:#fff3e0
