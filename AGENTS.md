# Project Voyager: Agent Context

## Project purpose

Project Voyager is a local-first desktop workspace for learning guitar, documenting practice, developing original compositions and curriculum, and connecting learning milestones with NASA's Voyager mission. The learner owns all creative and educational decisions. The initial reference composition is "Leaving Earth" in A minor, using Am and E at 60 BPM in 4/4.

## Current implementation

- Python 3 and PySide6 application launched with `python main.py`.
- `main.py` owns application startup and the PySide6 UI; `voyager/storage.py` handles SQLite and local attachments, while `voyager/ai_exchange.py` handles JSON briefs and response validation.
- SQLite and attachments are stored under Qt's application data location.
- The starter UI provides diary fields, composition/curriculum/mission text fields, attachment preview/open, and basic AI brief export/import.
- `requirements.txt` currently declares PySide6 only.
- The root ignore rules are currently in a file named `gitignore`, not `.gitignore`. The repository also tracks a local `.venv`; do not remove tracked environment files without explicit approval.

## Development guidelines

- Preserve existing user data and working behavior. Never delete or overwrite diary data or media as part of routine changes.
- Keep the initial application local-first. Do not add a paid AI API, provider-specific coupling, or network requirement without explicit product approval.
- Prefer small, incremental changes. Keep UI, domain logic, and persistence separable and testable as the application evolves; avoid a wholesale rewrite.
- Use responsive Qt layouts and centralized styling. Maintain the midnight-blue / subtle Voyager-gold studio aesthetic.
- Use SQLite parameter binding, explicit transaction boundaries, and clear error reporting for persistence operations.
- Validate imported JSON and show a review/confirmation step before applying AI suggestions. Keep learner-authored information intact.
- Keep media local and avoid embedding private learning data in source control or logs.
- Update `REQUIREMENTS.md` when product scope or delivery status changes, and `ROADMAP.md` when milestones change.
- Add focused tests for business logic and persistence before expanding the UI. Use the existing virtual environment when available; install dependencies only when required.
