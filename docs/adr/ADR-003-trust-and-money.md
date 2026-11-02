# Authoritative calculations

**Status:** Accepted  
**Context:** EnergyIQ RD is a portfolio-quality electricity intelligence product with production-oriented backend and applied AI requirements.

## Decision
Pure deterministic domain logic is sole authority for kWh, tariff arithmetic and confirmed bill data.

## Why
LLM output is probabilistic and susceptible to hallucinations.

## Alternatives considered
- More complex distributed/dependent architecture from day one.
- Simpler one-off prototype without production concerns.

## Consequences
LLM extracts proposals and explains verified facts; audit corrections and source evidence.

## Revisit trigger
When a product requirement, benchmark, or deployment constraint shows this decision should change.
