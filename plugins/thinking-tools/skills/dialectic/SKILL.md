---
name: dialectic
description: Prove and counter-prove a statement using parallel agents to eliminate confirmation bias. Use when someone says "dialectic", "prove/disprove", "stress test this claim", "is this really true", "argue both sides", or when a statement needs objective analysis from opposing viewpoints.
---

# Dialectic Analysis

Objective analysis of a statement by running two agents with opposing goals in parallel, then synthesizing findings.

## Process

### Step 1: Launch Parallel Agents

**CRITICAL: The MAIN orchestrator launches exactly TWO fresh `general` child
sessions in parallel**, one thesis and one antithesis. Use the actual V2
`subagent` tool with fields `agent`, `description`, `prompt`; omit session reuse
and model overrides unless the user selected a model. Submit both independent
foreground calls concurrently (one parallel tool batch / awaited concurrent
Code Mode calls using the tools actually exposed). Do not launch sequentially,
create a third synthesis agent, or delegate fanout to a child. General cannot
launch nested subagents. If invoked inside a child, return the two fully rendered
requests to the main orchestrator, not a pretend local debate.

Before dispatch, resolve the claim from the current request/command arguments
(ask if missing), workspace and evidence scope. Both prompts MUST explicitly
include: the exact claim, absolute working directory, relevant file paths/diff
or dataset and timeframe, applicable instructions with scopes, constraints,
known observations and counter-evidence, and required output format. Fresh
children do not inherit conversation history. Give both the same factual
context, differing only in the opposing role below. Require read-only research,
no edits/publications/nested fanout, specific citations, reproducible checks,
assumptions and evidence gaps. Do not demand fabricated support when none exists.

**Agent 1 (Thesis)** — find all POSITIVE evidence:
- what works well, improvements, correct patterns
- supporting facts, proof the statement is TRUE
- benefits, strengths, successful outcomes

**Agent 2 (Antithesis)** — find all NEGATIVE evidence:
- what's problematic, issues, risks, anti-patterns
- edge cases, proof the statement is FALSE
- weaknesses, failure modes, hidden costs

Both agents must provide specific file paths and line numbers when analyzing code.

### Step 2: Synthesize

After both agents complete, synthesize findings into an objective conclusion:
- weigh evidence from both sides
- identify where thesis and antithesis agree (strongest signal)
- note unresolved tensions
- distinguish conditional/happy-path support from a universal claim. A concrete
  counterexample can defeat a universal claim despite many passing examples.
- If either child fails or its output is truncated, disclose the incomplete
  analysis; do not call one-sided output a completed dialectic.

### Step 3: Verify

**CRITICAL** — form a provisional synthesis, then verify it against actual implementation before presenting the final conclusion:
- read the specific files and line numbers referenced by both agents
- confirm the evidence cited actually exists in the codebase
- check the implementation flow matches the claims made
- verify the synthesis accurately reflects the actual code context
- identify any misinterpretations or missing context from agent reports
- revise synthesis if verification reveals inaccuracies
- The main orchestrator performs this verification itself using `read`, `grep`
  and bounded `shell` checks; cite verified locations and separate observed
  results from inference. Unsupported/misquoted citations must not survive into
  the conclusion. If verification cannot be done, explicitly mark it unverified.

## Use Cases

**Architecture decisions:**
```
/dialectic this microservice split improves maintainability
```

**Bug analysis:**
```
/dialectic the connection pool fixes the timeout issue
```

**Performance claims:**
```
/dialectic caching reduced database load by 80%
```

**Refactoring safety:**
```
/dialectic extracting this interface simplifies testing
```

**Code review:**
```
/dialectic this implementation is thread-safe
```

**Review changes:**
```
/dialectic review the changes in server.go
```

## Key Principles

- **Eliminate confirmation bias** — examining both sides simultaneously prevents anchoring on the first conclusion
- **Evidence-based** — agents must cite specific files, lines, and facts, not general claims
- **Verification required** — synthesis must be checked against actual code before presenting
- **Objective conclusion** — the goal is truth, not winning either side
