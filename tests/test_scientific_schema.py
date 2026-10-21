"""Tests for schemas/scientific_tool_schema.json and adapters/rosetta_adapter.py.

Run: python -m pytest tests/test_scientific_schema.py
`jsonschema` is optional; full-schema checks are skipped when it is absent.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.rosetta_adapter import (  # noqa: E402
    SchemaError,
    load_schema,
    rosetta_to_record,
    validate_record,
)

SUCCESS_RESULT = {
    "status_code": "success",
    "designs": [
        {"pdb": "out/d1.pdb", "sequence": "MKTAYIAKQR", "score_dict": {"total_score": -312.4}},
        {"pdb": "out/d2.pdb", "sequence": "MKTAYLAKQR", "score_dict": {"total_score": -290.0}},
    ],
}


def _ok_record():
    return rosetta_to_record(
        act_name="rotamer_change",
        act_args={"residue_selectors": "<Index name='a' resnums='1'/>", "nstruct": 2},
        action_result=SUCCESS_RESULT,
        call_id="t-1",
        backend="mock",
        started_at="2026-10-21T00:00:00+00:00",
        step_index=0,
    )


def _jsonschema_validator():
    jsonschema = pytest.importorskip("jsonschema")
    return jsonschema, jsonschema.Draft202012Validator(load_schema())


def test_schema_file_is_valid_json_schema():
    jsonschema, _ = _jsonschema_validator()
    jsonschema.Draft202012Validator.check_schema(load_schema())


def test_valid_tool_call_serialisation_roundtrip():
    rec = _ok_record()
    validate_record(rec)
    restored = json.loads(json.dumps(rec))
    assert restored == rec
    assert restored["tool_name"] == "rosetta.rotamer_change"
    assert restored["status"] == "success"
    assert restored["result"]["units"] == "REU"
    assert restored["result"]["value"]["sequence"] == "MKTAYIAKQR"  # lowest total_score
    types = {i["name"]: i["type"] for i in restored["inputs"]}
    assert types == {"residue_selectors": "xml", "nstruct": "integer"}


def test_valid_record_passes_full_json_schema():
    _, validator = _jsonschema_validator()
    validator.validate(_ok_record())


@pytest.mark.parametrize("field", ["tool_name", "tool_version", "inputs", "execution_context"])
def test_malformed_missing_required_field(field):
    rec = _ok_record()
    del rec[field]
    with pytest.raises(SchemaError):
        validate_record(rec)


def test_malformed_missing_required_field_full_schema():
    jsonschema, validator = _jsonschema_validator()
    rec = _ok_record()
    del rec["tool_name"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(rec)


def test_malformed_input_item_and_adapter_inputs():
    rec = _ok_record()
    del rec["inputs"][0]["type"]
    with pytest.raises(SchemaError):
        validate_record(rec)
    with pytest.raises(SchemaError):
        rosetta_to_record(act_name="", act_args={}, action_result=SUCCESS_RESULT, call_id="x")
    with pytest.raises(SchemaError):
        rosetta_to_record(act_name="score_pdb", act_args={}, action_result={}, call_id="x")


def test_failed_execution_result():
    stderr = "line a\nERROR: Unrecognized residue selector 'core'\n at Mover.cc:121"
    rec = rosetta_to_record(
        act_name="backbone_change",
        act_args={"mover_name": "shear"},
        action_result={"status_code": "runtime_error", "stderr": stderr},
        call_id="t-2",
        backend="mock",
    )
    validate_record(rec)
    assert rec["status"] == "error"
    assert "result" not in rec
    assert rec["error"]["code"] == "runtime_error"
    assert rec["error"]["message"] == "line a"
    assert "Mover.cc:121" in rec["error"]["traceback_summary"]
    try:
        _, validator = _jsonschema_validator()
    except pytest.skip.Exception:
        return
    validator.validate(rec)


def test_unknown_status_maps_to_unknown_error_code():
    rec = rosetta_to_record(act_name="score_pdb", act_args={},
                            action_result={"status_code": "none"}, call_id="t-3")
    validate_record(rec)
    assert rec["error"]["code"] == "unknown"


def test_result_and_error_together_rejected():
    rec = _ok_record()
    rec["error"] = {"code": "unknown", "message": "x"}
    with pytest.raises(SchemaError):
        validate_record(rec)


def test_evidence_preservation_provenance_non_empty():
    rec = _ok_record()
    prov = rec["result"]["provenance"]
    assert prov["source"]
    assert [a["uri"] for a in prov["artifacts"]] == ["out/d1.pdb", "out/d2.pdb"]

    stripped = copy.deepcopy(rec)
    stripped["result"]["provenance"]["artifacts"] = []
    with pytest.raises(SchemaError):
        validate_record(stripped)


def test_success_without_evidence_is_downgraded_to_error():
    rec = rosetta_to_record(
        act_name="rotamer_change",
        act_args={},
        action_result={"status_code": "success", "designs": [{"sequence": "MK"}]},
        call_id="t-4",
    )
    validate_record(rec)
    assert rec["status"] == "error"
    assert "evidence" in rec["error"]["message"]


def test_provenance_sha256_recorded_for_existing_file(tmp_path):
    pdb = tmp_path / "d.pdb"
    pdb.write_text("ATOM      1  N   MET A   1\n")
    rec = rosetta_to_record(
        act_name="score_pdb", act_args={},
        action_result={"status_code": "success",
                       "designs": [{"pdb": str(pdb), "score_dict": {"total_score": -1.0}}]},
        call_id="t-5",
    )
    art = rec["result"]["provenance"]["artifacts"][0]
    assert len(art["sha256"]) == 64


def test_real_backend_rejects_missing_evidence():
    rec = rosetta_to_record(act_name="score_pdb", act_args={},
        action_result={"status_code": "success", "designs": [
            {"pdb": "this_file_does_not_exist_9b38.pdb", "score_dict": {"total_score": -1.0}}]},
        call_id="missing", backend="local")
    assert rec["status"] == "error"
    assert "missing" in rec["error"]["message"]


def test_missing_score_cannot_win_selection():
    rec = rosetta_to_record(act_name="score_pdb", act_args={},
        action_result={"status_code": "success", "designs": [
            {"pdb": "mock/a.pdb", "sequence": "A", "score_dict": {}},
            {"pdb": "mock/b.pdb", "sequence": "B", "score_dict": {"total_score": 12.0}}]},
        call_id="scores", backend="mock")
    assert rec["result"]["value"]["sequence"] == "B"
    assert "SIMULATED" in rec["result"]["provenance"]["notes"]


def test_nonfinite_or_missing_scores_rejected():
    for scores in ({}, {"total_score": float("nan")}):
        with pytest.raises(SchemaError):
            rosetta_to_record(act_name="score_pdb", act_args={},
                action_result={"status_code": "success", "designs": [
                    {"pdb": "mock/a.pdb", "score_dict": scores}]},
                call_id="invalid", backend="mock")
