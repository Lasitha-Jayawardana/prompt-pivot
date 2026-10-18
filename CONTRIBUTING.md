# Contributing

- `uv venv && uv pip install -e . --group dev`
- `pytest` runs the suite on SQLite (sync + async). Set `PROMPTPIVOT_TEST_POSTGRES_URL` and
  `PROMPTPIVOT_TEST_MYSQL_URL` to run it against real servers; CI does both.
- `mypy` (strict) and `ruff check` / `ruff format` must pass.
- Schema changes ship as a new file in `src/promptpivot/migrations/versions/` whose `upgrade`
  and `downgrade` accept a `prefix` keyword. Never edit an existing migration.
- Keep the core dependency list to SQLAlchemy, Pydantic, Jinja2 and FastAPI. Anything else goes in
  an extra.
