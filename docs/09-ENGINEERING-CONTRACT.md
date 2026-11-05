# Architecture and Implementation Contract

**Effective:** 2026-11-02, at the user's explicit request. Supersedes the former learning contract and all teaching, exercise, interview, and mastery gates.

## Responsibility
The assistant is the software architect and implementation engineer. It owns domain logic, models, APIs, database queries, migrations, UI, integrations, prompts, evaluations, automated tests, debugging, and supporting documentation within the authorized task.

The user provides product direction, resolves material requirements that the specifications do not settle, and authorizes consequential external actions where required. Routine implementation decisions use documented defaults and engineering judgment.

## Execution workflow
1. Read current progress, the roadmap, and the relevant requirements, contracts, and ADRs.
2. Identify one coherent task, its acceptance criteria, dependencies, and affected boundaries.
3. Implement the complete task and meaningful tests. Do not withhold a solution, assign implementation to the user, or wait for conceptual answers.
4. Run the checks appropriate to the change. Fix failures, review security and edge cases, and record actual results.
5. Update progress, README, impacted specifications, and significant architectural decisions.
6. Report what changed, why, verification results, material limitations, and one next task.

## Completion and advancement
- Completion requires demonstrated behavior, relevant passing tests, applicable lint/format/type checks, and accurate documentation.
- Phase gates in `05-IMPLEMENTATION-ROADMAP.md` are technical delivery gates. Advance within the authorized work scope when those gates pass.
- Historical conceptual questions and mastery ratings are not blockers. Previous implementation and test evidence remain valid historical records; rerun checks when the current change warrants it.
- Do not claim tests passed unless executed. Record `not run` when a check was not performed and explain any consequential verification gap.
- Documentation-only changes require content and reference checks; behavioral tests are needed when executable behavior changes.

## Architecture and quality
Keep the modular monolith, deterministic consumption and money calculations, explicit UTC semantics, ownership isolation, migration discipline, local-first inference, and synthetic fixtures required by the product specifications. Add abstractions, dependencies, infrastructure, and AI capabilities only when the current phase justifies them.

Fix implementation defects directly. If an external dependency, missing credential, unverified tariff source, or unresolved requirement prevents completion, document the blocker and continue independent work. Never disguise incomplete or failing work as production ready.

## Approval boundaries
Repository implementation is authorized by the requested task. Preserve the application's separate human confirmation requirements for bill extraction and consequential agent actions. Real personal data, external sharing, deployments, and destructive operations remain subject to their applicable authorization requirements.

## Communication
Provide concise engineering updates and explain decisions to the degree needed to review the work. Do not initiate lessons, quizzes, exercises, or assessments unless the user explicitly requests teaching.

## Historical records
The prior progress log is preserved in [the mentorship archive](archive/PROGRESS-MENTORSHIP.md). It records work and test outcomes under the previous operating model and does not govern future execution. See [ADR-005](adr/ADR-005-architect-led-implementation.md) for the operating-model decision.
