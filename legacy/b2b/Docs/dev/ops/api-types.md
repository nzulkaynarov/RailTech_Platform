# Type-safe frontend ↔ backend contract (OpenAPI → TS)

A whole class of silent bugs is field-name drift: the backend renames or reshapes
a response field, the frontend keeps reading the old name, gets `undefined`, and
the UI quietly breaks. Generating the frontend's API types from the backend's
OpenAPI schema turns those into **compile errors** instead.

`drf-spectacular` is already installed, so the backend can emit the schema; we
generate TS types from it with `openapi-typescript`.

## One-time setup

```bash
cd frontend
npm i -D openapi-typescript        # commit the updated package-lock.json
```

## Generate

```bash
# 1. Emit the OpenAPI schema from the backend (inside the backend container/env)
docker compose exec backend python manage.py spectacular \
  --file /app/schema.openapi.json --format openapi-json
# copy it to backend/schema.openapi.json (or generate straight to that path)

# 2. Generate the TS types
cd frontend
npm run gen:api-types              # → src/api/schema.d.ts
```

## Use

Import the generated `components['schemas'][...]` types in the axios api modules
(`src/api/*.ts`) instead of hand-written interfaces, so response shapes are
checked against the real backend contract at `tsc` time.

## Make it routine (optional)

Once adopted, add a CI job that regenerates the schema + types and fails if
`git diff` is non-empty — that flags any backend change that wasn't reflected on
the frontend before it ships.
