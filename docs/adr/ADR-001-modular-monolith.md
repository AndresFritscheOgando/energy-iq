# Modular monolith

**Status:** Accepted  
**Context:** EnergyIQ RD is a portfolio-quality electricity intelligence product with production-oriented backend and applied AI requirements.

## Decision
One FastAPI deployable with internal domain modules.

## Why
Keep domain logic and AI integrations within one deployable to limit operational complexity while preserving internal boundaries.

## Alternatives considered
- More complex distributed/dependent architecture from day one.
- Simpler one-off prototype without production concerns.

## Consequences
Preserve boundaries and tests; extract services only with measured justification.

## Revisit trigger
When a product requirement, benchmark, or deployment constraint shows this decision should change.
