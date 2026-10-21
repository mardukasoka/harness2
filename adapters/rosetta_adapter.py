"""Minimal adapter: Agent-Rosetta style action results -> common scientific tool schema.

Standard library only; no Rosetta install, GPU, or paid API needed. The input shape
mirrors `environments/rosetta/typing.py::RosettaActionResults` and
`environments/rosetta/state.py::RosettaDesign` in PolymathicAI/agent-rosetta
(status_code, stderr, designs[{pdb, sequence, score_dict}]), passed as plain dicts
so this module does not import agent-rosetta or pydantic.

Run standalone:  python adapters/rosetta_adapter.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "scientific_tool_schema.json"
SCHEMA_VERSION = "1.0.0"

# Rosetta status codes (agent-rosetta RosettaStatusCode) -> schema error codes.
_ERROR_CODES = {
    "validation_error": "validation_error",
    "resource_error": "resource_error",
    "runtime_error": "runtime_error",
    "transport_error": "transport_error",
    "timeout": "timeout",
}
_PY_TYPES = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
    list: "array",
    dict: "object",
}
REQUIRED_TOP = ("schema_version", "call_id", "tool_name", "tool_version", "inputs",
                "execution_context", "status")


class SchemaError(ValueError):
    """Raised when a record or adapter input violates the common schema."""


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _typed(name: str, value: object) -> dict:
    kind = _PY_TYPES.get(type(value), "string")
    if isinstance(value, str) and value.lstrip().startswith("<"):
        kind = "xml"  # Rosetta args carry XML residue selectors / mover params.
    return {"name": name, "type": kind, "value": value, "units": None}


def _sha256(path: str) -> str | None:
    p = Path(path)
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return None


def _summarise_traceback(stderr: str | None, limit: int = 20) -> str | None:
    """Keep the tail of stderr (where Rosetta reports the failing mover/exception)."""
    if not stderr:
        return None
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    return "\n".join(lines[-limit:])[:4000]


def rosetta_to_record(
    *,
    act_name: str,
    act_args: dict,
    action_result: dict,
    call_id: str,
    tool_version: str = "agent-rosetta-0.1.0",
    backend: str = "local",
    started_at: str | None = None,
    finished_at: str | None = None,
    step_index: int | None = None,
    score_term: str = "total_score",
) -> dict:
    """Map one Rosetta action result to a ScientificToolRecord dict."""
    if not act_name:
        raise SchemaError("act_name is required")
    if not isinstance(act_args, dict):
        raise SchemaError("act_args must be a dict")
    if "status_code" not in action_result:
        raise SchemaError("action_result.status_code is required")

    ctx: dict = {"started_at": started_at or _now(), "backend": backend, "environment": "rosetta"}
    if finished_at:
        ctx["finished_at"] = finished_at
    if step_index is not None:
        ctx["step_index"] = step_index

    record: dict = {
        "schema_version": SCHEMA_VERSION,
        "call_id": str(call_id),
        "tool_name": f"rosetta.{act_name}",
        "tool_version": tool_version,
        "inputs": [_typed(k, v) for k, v in act_args.items()],
        "execution_context": ctx,
    }

    status = action_result["status_code"]
    designs = action_result.get("designs") or []
    if status == "success" and designs:
        artifacts = []
        for d in designs:
            if d.get("pdb"):
                art = {"uri": str(d["pdb"]), "role": "decoy_pdb"}
                digest = _sha256(str(d["pdb"]))
                if digest:
                    art["sha256"] = digest
                artifacts.append(art)
        if not artifacts:
            # Evidence preservation: a success with no artefact is downgraded to an error.
            status = "runtime_error"
            action_result = {**action_result, "stderr": "success reported without decoy PDB evidence"}
        else:
            best = min(designs, key=lambda d: float((d.get("score_dict") or {}).get(score_term, 0.0)))
            metrics = {k: float(v) for k, v in (best.get("score_dict") or {}).items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)}
            record["status"] = "success"
            record["result"] = {
                "value": {"sequence": best.get("sequence"), score_term: metrics.get(score_term)},
                "units": "REU",  # Rosetta Energy Units
                "metrics": metrics,
                "provenance": {
                    "source": f"Rosetta via {tool_version}",
                    "artifacts": artifacts,
                    "notes": f"{len(designs)} design(s); best by min {score_term}",
                },
            }
            return record
    elif status == "success":
        status = "runtime_error"
        action_result = {**action_result, "stderr": "success reported without designs"}

    record["status"] = "error"
    record["error"] = {
        "code": _ERROR_CODES.get(status, "unknown"),
        "message": (action_result.get("stderr") or f"Rosetta action failed: {status}").strip()
        .splitlines()[0][:500],
        "traceback_summary": _summarise_traceback(action_result.get("stderr")),
    }
    return record


def validate_record(record: dict) -> None:
    """Dependency-free structural check of the schema's key invariants.

    Use `jsonschema` with `load_schema()` for full validation when it is installed.
    """
    missing = [k for k in REQUIRED_TOP if k not in record]
    if missing:
        raise SchemaError(f"missing required fields: {missing}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise SchemaError("unsupported schema_version")
    if not isinstance(record["inputs"], list):
        raise SchemaError("inputs must be a list")
    for item in record["inputs"]:
        for key in ("name", "type", "value"):
            if key not in item:
                raise SchemaError(f"input missing '{key}': {item}")
    ctx = record["execution_context"]
    if "started_at" not in ctx or "backend" not in ctx:
        raise SchemaError("execution_context requires started_at and backend")
    status = record["status"]
    if status == "success":
        if "result" not in record or "error" in record:
            raise SchemaError("success requires result and forbids error")
        res = record["result"]
        for key in ("value", "units", "provenance"):
            if key not in res:
                raise SchemaError(f"result missing '{key}'")
        prov = res["provenance"]
        if not prov.get("source") or not prov.get("artifacts"):
            raise SchemaError("provenance.source and non-empty provenance.artifacts required")
    elif status == "error":
        if "error" not in record or "result" in record:
            raise SchemaError("error status requires error and forbids result")
        if not record["error"].get("code") or not record["error"].get("message"):
            raise SchemaError("error requires code and message")
    else:
        raise SchemaError(f"invalid status {status!r}")


def _demo() -> int:
    ok = rosetta_to_record(
        act_name="rotamer_change",
        act_args={"residue_selectors": "<Index name='core' resnums='1-10'/>",
                  "packing_restrictions": ""},
        action_result={
            "status_code": "success",
            "designs": [
                {"pdb": "out/design_0001.pdb", "sequence": "MKTAYIAKQR",
                 "score_dict": {"total_score": -312.4, "fa_atr": -540.1}},
                {"pdb": "out/design_0002.pdb", "sequence": "MKTAYLAKQR",
                 "score_dict": {"total_score": -298.0, "fa_atr": -530.7}},
            ],
        },
        call_id="demo-1", backend="mock", step_index=1,
    )
    bad = rosetta_to_record(
        act_name="backbone_change",
        act_args={"mover_name": "shear"},
        action_result={"status_code": "runtime_error",
                       "stderr": "ERROR: [ERROR] Unrecognized residue selector 'core'\n"
                                 "  at protocols/moves/Mover.cc:121"},
        call_id="demo-2", backend="mock", step_index=2,
    )
    for rec in (ok, bad):
        validate_record(rec)
        print(json.dumps(rec, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_demo())
