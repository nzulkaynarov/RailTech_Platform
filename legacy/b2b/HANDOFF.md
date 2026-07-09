# AI Agent Handoff Document

## Overview
This document serves as a memory checkpoint for AI agents picking up work on the **RailTech SaaS B2B** project. It outlines the recent changes made, resolved infrastructure bugs, UI/UX improvements, and the current state of the application.

## 1. Recent Work Completed
### 1.1. Deep UX/UI Refactoring (Profile & Settings)
We audited and refactored the following tabs in the B2B Cabinet (`frontend/src/components/Cabinet/`):
- **Команда (CompanyTeamSettings.tsx):** Added a "Закрыть" (Close) button to the footer of the system role sheet (Sheet).
- **Шаблоны расходов (ChargeTemplatesSettings.tsx):** Implemented an `AlertDialog` for deletion confirmation to prevent accidental removals.
- **Документы и бренд (CompanyDocumentProfileSettings.tsx):** Improved the "Использовать данные профиля компании" checkbox behavior. When checked, the inputs are strictly disabled and visually grayed out. When unchecked, they remain interactive.
- **Дефолты КП (CompanyDefaultsSettings.tsx):** Added strict client-side validation for VAT (НДС) and Margins (Маржа). Inputs are restricted to the 0-100 range.
- **Нумерация документов (CompanyNumberingSettings.tsx):** Added a sanitizer for prefixes to automatically strip out special characters.

### 1.2. Backend Infrastructure & Docker Fixes
- **Celery Modules:** Resolved `ModuleNotFoundError` for `pyotp` and `greenlet` by adding them to `backend/requirements.in`.
- **Dependency Hashes:** Fixed a pip install failure in Docker (`--require-hashes` error) by recompiling `requirements.txt` with `uv pip compile --generate-hashes backend/requirements.in -o backend/requirements.txt`.
- All containers (`docker compose up`) are now building cleanly and reporting as `healthy`.

### 1.3. Frontend Bugs Resolved
- Fixed a TypeScript syntax error in `frontend/src/store/authStore.ts` where the backend response key `2fa_required` was invalidly mapped as `data.2fa_required`. Changed to `data['2fa_required']`.

## 2. Current State
- The application runs reliably via `docker compose`. 
- The backend serves API endpoints at `localhost:8000`.
- The frontend (Vite) runs locally via `npm run dev -- --port 5174` (or 5173 when built via Nginx).
- Local email delivery (for password setup/registration) writes links to the `railtech_backend` docker container logs (can be retrieved via `docker logs railtech_backend`). 

## 3. Recommended Next Steps
1. **Verification & Testing:** The immediate next step is to continue end-to-end verification of the UI refactoring. Register a new user, fetch the setup password link from the backend logs, and manually verify the updated tabs in the settings menu.
2. **Continue Refactoring:** Apply the generated "Gemini Flash TZ" (Technical Specification) to any remaining modules that lack a premium UI/UX feel, particularly focusing on micro-interactions, responsive padding, and validation states.
3. **Check Artifacts:** Note that a comprehensive UX audit report and screenshots have been generated in previous sessions. They outline the expected standard of "World-class B2B UI/UX."

## 4. Helpful Commands
- Fetch registration email link: `docker logs railtech_backend | grep "setup-password"`
- Restart containers: `docker compose down && docker compose up --build -d`
- Run frontend dev server: `cd frontend && npm run dev -- --port 5174`
