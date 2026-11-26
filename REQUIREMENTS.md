# Project Voyager Requirements

## Product direction

Build a cross-platform, local-first guitar learning studio in Python 3 with PySide6 and SQLite. It should connect the learner's real practice, compositions, and future curriculum to Voyager mission milestones, with optional provider-independent AI collaboration and no paid AI API requirement for the initial version.

Status reflects the repository inspected on 2026-11-25.

## Functional requirements

| Area | Requirement | Status |
|---|---|---|
| Learning diary | Create, edit, and organize daily or weekly learning entries with chords, techniques, concepts, duration, challenges, observations, and accomplishments. | Partial: entries can be created/edited and include general notes/reflection fields; weekly organization and structured practice fields are absent. |
| Learning diary | Attach images, audio, video, PDFs, and reference links; provide a chronological timeline. | Partial: local image/video/audio/PDF attachments and date-sorted entries exist; reference links and a dedicated timeline are absent. |
| Composition studio | Manage compositions with chord progressions, tempo, time signature, structure, AI suggestions, revisions, and recordings. | Partial: compositions are free-text per diary entry and media can be attached; structured metadata, revision history, and composition-specific management are absent. |
| Score playback | Provide a count-in and optional accompaniment to support playing along locally. | Partial: MusicXML playback has an optional 120 BPM count-in and locally synthesized percussion, bass and approximate per-measure chords. The score's own tempo and tempo changes drive playback and backing; accompaniment is included in video export. Chord inference is not a substitute for an authored arrangement. |
| Score playback | Use locally available violin recordings for expressive playback. | Partial: bundled CC0 VSCO 2 CE sustained samples and alternating short-bow takes support explicitly marked MusicXML staccato, staccatissimo and spiccato. MIDI-driven playback does not transfer MusicXML articulations; other articulations and learner-recorded instruments are not yet supported. |
| Voyager timeline | Associate milestones with historical mission events, descriptions, dates, imagery, sources, and compositions. | Partial: a mission text field exists; mission-event records, sourced timeline, and composition links are absent. |
| AI collaboration | Export learning progress as JSON; import exercises, ideas, and curriculum recommendations; preview before accepting; retain human ownership; remain provider-independent. | Partial: a selected entry can be exported/imported as JSON and suggestions are appended after confirmation; there is no structured preview or full-progress export. No paid API is present. |
| Curriculum builder | Turn diary entries into lessons with difficulty, technique/concept, objectives, exercises, and assessment criteria. | Partial: curriculum notes are free text; there is no structured lesson builder. |
| Dashboard | Show progress/statistics, recent entries and compositions, current mission milestone, and quick actions. | Not implemented: the application opens directly to the diary editor. |
| User experience | Provide a responsive Qt interface with a collapsible navigation sidebar, reusable widgets, centralized theme, and a polished Voyager-inspired visual identity. | Partial: dark styling and responsive layouts are present; navigation is a fixed list/actions column, and styling is inline rather than centralized. |
| Platform and storage | Use Python 3, PySide6, SQLite, local media, and cross-platform-compatible paths. | Partial: persistence and JSON exchange are separated from the UI, and Qt application-data paths are in use; broader modularization and platform validation remain. |

## Initial learning milestone

- Project: Voyager
- Composition: Leaving Earth
- Instrument: Acoustic guitar
- Chords: A minor and E major
- Tempo and meter: 60 BPM, 4/4
- Progression: `Am | Am | E | E | Am | E | E | Am`
- Mission theme: Earth and Moon

The application currently seeds a related Am/E lesson and composition suggestion, but its date and learner observations are hard-coded. Confirm provenance and avoid representing seeded claims as verified practice history.

## Engineering requirements

- Keep UI, business logic, and persistence independently testable as implementation grows.
- Preserve existing diary records and attachment files during migrations and refactors.
- Validate imported data, retain original learner content, and report failures explicitly.
- Keep AI exchange data structured and provider-neutral; make no network/API dependency mandatory.
- Add automated tests for persistence, import/export, and core domain behavior.
- Keep dependency additions minimal and document setup and supported Python versions.
