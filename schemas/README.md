# Scientific tool-call schema (v1.0.0)

`scientific_tool_schema.json` (JSON Schema draft 2020-12) is a common envelope for one scientific tool call and its outcome.

| Field | Meaning |
|---|---|
| `schema_version` | Always `1.0.0` for this version. |
| `call_id` | Unique id for the call (trajectory node index or UUID). |
| `tool_name` / `tool_version` | Namespaced tool id (e.g. `rosetta.rotamer_change`) and the version that ran. |
| `inputs[]` | Typed named inputs: `name`, `type` (string/integer/number/boolean/array/object/file/xml/sequence), `value`, optional `units`. |
| `execution_context` | `started_at`, `backend` (local/slurm/ray/container/remote_api/mock), plus optional `finished_at`, `duration_s`, `host`, `environment`, `step_index`, `parent_call_id`, `seed`. |
| `status` | `success` or `error`. A record has exactly one of `result` or `error`. |
| `result` | `value`, `units` (null = dimensionless), optional numeric `metrics`, and required `provenance` (`source` and a non-empty `artifacts[]` list of `{uri, sha256?, role?}`). |
| `error` | `code` (validation_error/resource_error/runtime_error/transport_error/timeout/unknown), `message`, `traceback_summary` (stderr tail, ≤4000 chars). |

## How adapters should use it
1. Map native arguments to `inputs[]` without losing their types.
2. Put native status codes into `error.code`. Anything not recognised becomes `unknown`.
3. Never report `success` unless there is evidence. If no artifact exists, return an error instead (`adapters/rosetta_adapter.py` does this).
4. Check records with `jsonschema` against this file. If `jsonschema` is not installed, use the stdlib `validate_record` helper.

Example: `python adapters/rosetta_adapter.py`; tests: `python -m pytest tests/test_scientific_schema.py`.
