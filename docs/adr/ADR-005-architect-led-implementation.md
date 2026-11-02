# Architect-led implementation

**Status:** Accepted  
**Date:** 2026-11-02  
**Context:** The user explicitly replaced the repository's mentorship workflow with direct architecture and implementation responsibility for the assistant.

## Decision
The assistant acts as architect and implementation engineer, delivering complete features, tests, evaluations, fixes, and documentation according to the existing product specifications and roadmap. Teaching, user implementation assignments, quizzes, interviews, and mastery assessments are removed from delivery gates.

## Consequences
- `AGENTS.md` and the engineering contract define the implementation workflow.
- Advancement depends on verified technical acceptance criteria within the authorized task scope.
- Historical work and test evidence are preserved; old educational next actions are superseded.
- The architecture, phase order, privacy rules, ownership checks, deterministic calculations, human bill confirmation, and consequential application action approvals remain required.
- This decision changes the operating model; it does not mark unfinished features complete or authorize unrelated external actions.

## Revisit trigger
An explicit user request to change responsibilities or the delivery workflow.
