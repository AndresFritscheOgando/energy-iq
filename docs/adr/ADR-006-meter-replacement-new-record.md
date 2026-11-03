# Meter replacement creates a new Meter record

**Status:** Accepted  
**Date:** 2026-11-03  
**Context:** Phase 1 records a replacement as a `replaced` event inside one meter's reading chain. An approved event in a pair makes that pair a `meter_boundary` with no kWh, and a reading at the event instant starts the new segment. Under one meter ID, the old meter's final reading and the new meter's first reading cannot share an instant without a timestamp conflict, so at least one interval of real consumption is always lost, and the two physical registers are mixed in one chain. Decided in [spec 0007](../specs/0007-meter-semantics-discontinuity-rules/index.md); see the [meter semantics reference](../12-METER-SEMANTICS.md).

## Decision
From Phase 2, replacing a physical meter creates a new Meter record. The old meter gets a final reading and becomes inactive. The new meter gets an approved `installed` event and a first reading. The in chain `replaced` event stays supported for data already recorded under one meter ID.

## Consequences
- Each physical register keeps its own continuous chain, so neither the old final reading nor the new first reading is lost to a conflict.
- Phase 2 designs a link from the new Meter to the one it replaces, with its name, type, constraints, and migration, in its own spec.
- Window summaries and bill reconciliation for a property that spans a replacement must combine two meters' summaries; that is designed with Phase 4 reconciliation.
- Ownership checks apply to both Meter records; the replacement link never grants access to a meter the caller does not own.
- Creating the new Meter is a consequential write: model or tool output cannot do it without the confirmation and audit rules in the [security and operations document](../08-SECURITY-OPERATIONS.md).

## Revisit trigger
A data source that cannot identify the physical meter (for example an import with one account number across a replacement), or evidence that users record replacements more reliably as an event than as a new meter.
