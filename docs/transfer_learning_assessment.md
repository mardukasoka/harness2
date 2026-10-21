# Transfer-learning assessment (WS1)

Baselines inspected: agent-rosetta `main@3fe49a3`, harness2 `main@1cfe254`, the_well `master@aac88c0` (code only; no data downloaded).

## agent-rosetta components that could transfer to Inkling / Beam (hypothetical Indigo agent systems)
- **Action registry** (`agent_rosetta/action.py`: `ActionSpec`, `EnvironmentActions`): actions are pydantic-typed and generate their own docs. This works for any tool-using agent.
- **Environment ABC** (`agent_rosetta/environment.py`): `setup/reset/step` plus a deep-copied `EnvironmentState` with `status_code`/`stderr`.
- **Trajectory tree** (`agent_rosetta/trajectory.py`, `TrajectoryNode`): branching history with `go_back_to`. This maps directly to backtracking or timeline branching.
- **Status-code taxonomy** (`environments/rosetta/typing.py`: validation/resource/runtime/transport/timeout). The common schema's `error.code` uses it.
- **Parser/Runner/Model separation** with Hydra configs (`configs/`). The model is reached through litellm, so the agent logic does not depend on one provider.
- **Not transferable as-is:** Rosetta XML movers, ESMFold tools, and the PDB reward functions. These are specific to protein design.

## The Well for pre-training
- 16 datasets, about 15 TB of HDF5 spatiotemporal PDE simulations: MHD, acoustics, Euler, Rayleigh–Bénard, supernova, neutron-star merger and others. A `WellDataset` PyTorch loader and benchmark configs (FNO, AFNO, AViT, etc.) are included.
- It suits surrogate and foundation-model pre-training for physical fields (see the multiple_physics_pretraining fork). It does not train language or tool-use agents.

## Blockers
- **Compute:** the full data is 15 TB, and the benchmark training expects GPUs. This sandbox has neither, so nothing was downloaded or trained.
- **Licensing:** agent-rosetta is MIT; Rosetta itself needs a separate academic or commercial licence. The Well code is BSD-3, and per-dataset terms must be checked. harness2 is Apache-2.0, and the WorkBuddy third-party licence restricts EU use.
- **Data format:** The Well uses HDF5 grids; agent-rosetta uses PDB files and pydantic JSON. Bridging them needs field-level adapters; the common schema covers only call/result envelopes.
- **Model weights:** none are present in the inspected repos. ESMFold weights are fetched at runtime through transformers.
