# Local-first models

**Status:** Accepted  
**Context:** EnergyIQ RD is a portfolio-quality electricity intelligence product with production-oriented backend and applied AI requirements.

## Decision
Ollama by default behind provider interface.

## Why
Supports local inference and avoids uploading personal bills by default.

## Alternatives considered
- More complex distributed/dependent architecture from day one.
- Simpler one-off prototype without production concerns.

## Consequences
Quality and hardware limits require measured benchmarks; mock deterministic CI.

## Revisit trigger
When a product requirement, benchmark, or deployment constraint shows this decision should change.
