# Project Voyager Roadmap

The roadmap favors small, reversible steps and preserves the existing starter application. Do not begin a substantial architectural change until the project owner approves the proposed first milestone.

## Milestone 0: Repository baseline and project context

- [x] Inspect the existing application, dependency declaration, assets, and repository layout.
- [x] Record product scope, current implementation status, and development guidelines.
- [x] Defer ignore-file and tracked-virtual-environment cleanup per owner approval; no index or ignore changes were made.

## Milestone 1: Safe, testable application foundation — complete

- [x] Keep the 6,248 tracked `.venv` files and existing untracked IDE settings unchanged per owner approval.
- [x] Add focused standard-library tests for entry persistence, attachments, and JSON exchange.
- [x] Separate application startup, database access, and JSON exchange in incremental steps, without changing the user workflow.
- [x] Make database initialization and seeding idempotent; avoid inventing verified practice dates or observations.
- [x] Retain Qt application-data/media paths and add user-visible handling for persistence and import/export errors.
- [x] Keep the existing UI and stored records working throughout the transition.

**Acceptance:** focused tests pass; the app starts from the documented command; existing entries/media remain readable; no data is silently overwritten.

**Verified:** 11 focused tests pass, including compatibility with the existing SQLite schema and attachments; application startup and the Qt window run against temporary local data.

## Milestone 2: Structured diary and media workflow

- Add structured practice duration, chords, concepts, techniques, challenges, and accomplishments.
- Improve attachment metadata and add reference links while keeping files local.
- Support reliable chronological organization and clarify daily/weekly entry workflows.

## Milestone 3: Composition studio

- Add composition records with progression, tempo, meter, and musical structure.
- Link recordings and preserve revisions without overwriting learner-authored content.
- Retain the current "Leaving Earth" material as the initial example.

## Milestone 4: Voyager mission timeline

- Model dated mission events with descriptions and source references.
- Link learning milestones and compositions to events, beginning with the Earth and Moon theme.
- Add NASA imagery only with traceable source metadata.

## Milestone 5: Human-reviewed AI collaboration and curriculum

- Define versioned, validated JSON formats for progress export and suggestions.
- Present imported suggestions in a review surface before acceptance.
- Build structured curriculum lessons from learner-approved diary content.
- Keep providers optional and make no paid API necessary.

## Milestone 6: Dashboard and release readiness

- Add the progress dashboard and quick actions after the core records and metrics are stable.
- Centralize the theme, refine navigation, and validate responsive layouts.
- Add cross-platform smoke checks, backup guidance, and packaging only when the core workflow is dependable.
