# Full stack

**Status:** Accepted  
**Context:** EnergyIQ RD is a portfolio-quality electricity intelligence product with production-oriented backend and applied AI requirements.

## Decision
Next.js TypeScript frontend + FastAPI backend + PostgreSQL.

## Why
Separates browser interactions, typed backend services, and relational persistence with explicit production application boundaries.

## Alternatives considered
- More complex distributed/dependent architecture from day one.
- Simpler one-off prototype without production concerns.

## Consequences
Slightly larger scope; implement backend vertical slice before UI, defer complexity.

## Revisit trigger
When a product requirement, benchmark, or deployment constraint shows this decision should change.
