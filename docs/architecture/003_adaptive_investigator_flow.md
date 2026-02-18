# Adaptive Investigator Flow

This document details the interaction between the `Investigator` agent, the `AdaptiveExecutor`, and the `Internal Recovery Loop`.

## High-Level Architecture

The system uses a "Fail-Fast but Recover-Smart" approach. When a tool fails, instead of blindly retrying, we identify *why* it failed (Missing Dependency) and immediately attempt to find that information.

```mermaid
sequenceDiagram
    participant Sup as Supervisor
    participant Inv as Investigator
    participant AE as AdaptiveExecutor
    participant LLM as LLM (Diagnosis)
    participant ES as EvidenceStore

    Sup->>Inv: Route (Hypothesis: Verifying)
    Note over Inv: 1. Select Tool (e.g., Get DNAT)
    Inv->>AE: Execute(Tool, Args)
    
    rect rgb(255, 230, 230)
    Note over AE: Execution Loop
    AE->>AE: Run Tool -> Fails (424 Dependency)
    AE->>LLM: Diagnose & Fix?
    LLM-->>AE: "Missing Info: Device ID / Permissions"
    AE-->>Inv: RAISE MissingDependencyError
    end

    rect rgb(230, 255, 230)
    Note over Inv: Internal Recovery Loop
    Inv->>ES: Save Evidence "EXECUTION FAILED" (The original failure)
    Inv->>LLM: "Select Resolution Tool for missing info?"
    LLM-->>Inv: "Run fgt_get_system_status"
    
    alt Resolution Tool Found
        Inv->>AE: Execute(Resolution Tool)
        AE-->>Inv: Result (e.g., Device Serial)
        Inv->>ES: Save Evidence "Resolution Success"
        Note over Inv: Return. (Original tool NOT retried yet)
    else No Resolution Tool
        Inv->>ES: Save Evidence "BLOCKED: System Advisor"
    end
    end

    Inv->>Sup: Return State (Evidence Updated)
    
    Note over Sup: Next Iteration
    Sup->>Hyp: Re-evaluate Hypothesis
    Hyp->>Sup: Status: Verifying (unchanged/updated)
    Sup->>Inv: Route (Retry)
    
    Note over Inv: 2. Select Tool (Again)
    Inv->>Inv: Read Evidence. See "Resolution Success" (Fact Found).
    Inv->>AE: Execute(Tool, Args={Fixed Device ID})
    Note over AE: Success!
```

## detailed Components

### 1. AdaptiveExecutor
- **Role**: Wraps low-level tool execution.
- **Behavior**:
    - Retries transient errors (timeouts).
    - Uses LLM to diagnose schema errors.
    - **Crucial**: If it detects missing *context* (e.g., "I need an IP, you gave me a hostname"), it does *not* halluciation. It raises `MissingDependencyError`.

### 2. Investigator (The Agent)
- **Role**: High-level planner of verification steps.
- **Behavior**:
    - Selects a tool based on the Hypothesis.
    - **Catching Failure**: When `AdaptiveExecutor` raises `MissingDependencyError`, the Investigator enters the **Internal Recovery Loop**.

### 3. Internal Recovery Loop (New)
- **Goal**: Don't just give up; try to fix the blocker *in-flight*.
- **Logic**:
    1.  The agent asks the LLM: *"What tool can I run NOW to get this missing info?"* (e.g., Discovery tools).
    2.  If found, it executes it immediately.
    3.  It saves the result as Evidence.
    4.  **Important**: It then *yields* back to the Supervisor.
        - *Why?* Because updating the state and letting the `Investigator` "think" freshly in the next turn (with the new Evidence in context) is more robust than trying to hot-fix the arguments blindly in code.

## Why Evidence Might Be "Missing"

In previous versions, when `MissingDependencyError` was caught, we saved a "System Advisor" note but *discarded* the original "Failed Tool" event.
**Correction**: The log now ensures two pieces of evidence are saved:
1.  `[Tool Name]`: EXECUTION FAILED (The 424/400 error).
2.  `[system_advisor]`: BLOCKED (The explanation of what is missing).

This ensures the Final Report shows "We tried X, it failed, so we looked for Y."
