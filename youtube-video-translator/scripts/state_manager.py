"""
Phase state manager for youtube-video-translator.
Provides checkpoint/resume functionality across sessions.
"""

import json
import os
from pathlib import Path
from typing import Optional

STATE_FILENAME = ".phase-state.json"
PHASE_NAMES = {
    0: "env_check",
    1: "intent_collection",
    2: "setup",
    3: "metadata_caption_download",
    4: "subtitle_pipeline",
    5: "voiceover",
    6: "cover",
    7: "compose",
    8: "upload_preview",
    9: "bilibili_publish",
    10: "cleanup",
}


def get_state_root(video_id: str) -> Path:
    """Return the translation root directory for a video."""
    return Path(f"./translations/{video_id}")


def get_state_path(video_id: str) -> Path:
    """Return path to the state file."""
    path = get_state_root(video_id) / STATE_FILENAME
    # print(f"DEBUG: state_path={path.resolve()}")
    return path


def load_state(video_id: str) -> dict:
    """
    Load state for a video. Returns a fresh state if none exists.
    """
    path = get_state_path(video_id)
    if path.exists():
        try:
            with open(path) as f:
                state = json.load(f)
                # print(f"[DEBUG] Loaded state from {path.resolve()}")
                return state
        except Exception as e:
            print(f"[WARNING] Failed to load state from {path}: {e}")

    # Return initial state
    return {
        "video_id": video_id,
        "current_phase": -1,
        "phase_status": "not_started",
        "completed_phases": [],
        "artifacts": {},
        "errors": [],
    }


def save_state(video_id: str, state: dict) -> None:
    """Save state to disk."""
    path = get_state_path(video_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        # 显式输出状态保存信息，以便 agent 和用户感知
        print(f"[DEBUG] State saved to: {path.resolve()}")
    except Exception as e:
        print(f"[ERROR] Failed to save state to {path}: {e}")


def update_phase(
    video_id: str,
    phase: int,
    status: str,
    artifact: Optional[str] = None,
    error: Optional[str] = None,
) -> dict:
    """
    Update state after completing (or failing) a phase.
    status: "running", "done", "failed", "skipped"
    """
    state = load_state(video_id)

    state["phase_status"] = status
    state["current_phase"] = phase
    state["errors"] = [item for item in state.get("errors", []) if item.get("phase") != phase]

    if status == "done" and phase not in state["completed_phases"]:
        state["completed_phases"].append(phase)

    if artifact:
        state["artifacts"][PHASE_NAMES.get(phase, f"phase_{phase}")] = artifact

    if error:
        state["errors"].append({
            "phase": phase,
            "error": error,
        })

    save_state(video_id, state)
    return state


def is_phase_completed(video_id: str, phase: int) -> bool:
    """Check if a specific phase has already been completed."""
    state = load_state(video_id)
    return phase in state.get("completed_phases", [])


def get_next_pending_phase(video_id: str) -> int:
    """Return the next phase that hasn't been completed yet."""
    state = load_state(video_id)
    completed = set(state.get("completed_phases", []))
    for phase in range(11):
        if phase not in completed:
            return phase
    return 11  # All done


def reset_state(video_id: str, from_phase: Optional[int] = None) -> dict:
    """
    Reset state from a given phase (inclusive). If from_phase is None,
    reset everything.
    """
    state = load_state(video_id)
    if from_phase is not None:
        state["completed_phases"] = [p for p in state.get("completed_phases", []) if p < from_phase]
        state["current_phase"] = max(state["completed_phases"]) if state["completed_phases"] else -1
        state["artifacts"] = {
            name: value
            for phase, name in PHASE_NAMES.items()
            if phase < from_phase and name in state.get("artifacts", {})
            for value in [state["artifacts"][name]]
        }
        state["errors"] = [
            err for err in state.get("errors", [])
            if err.get("phase", from_phase) < from_phase
        ]
        state["phase_status"] = "done" if state["completed_phases"] else "not_started"
    else:
        state["current_phase"] = -1
        state["completed_phases"] = []
        state["artifacts"] = {}
        state["errors"] = []
        state["phase_status"] = "not_started"

    save_state(video_id, state)
    return state


def get_artifacts(video_id: str) -> dict:
    """Return the artifacts dict for a video."""
    state = load_state(video_id)
    return state.get("artifacts", {})


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: state_manager.py <video_id> <action> [args...]")
        print("Actions: load, set-phase, is-completed, next-pending, reset")
        sys.exit(1)

    video_id = sys.argv[1]
    action = sys.argv[2]

    if action == "load":
        print(json.dumps(load_state(video_id), indent=2, ensure_ascii=False))
    elif action == "is-completed":
        phase = int(sys.argv[3])
        print("true" if is_phase_completed(video_id, phase) else "false")
    elif action == "next-pending":
        print(get_next_pending_phase(video_id))
    elif action == "reset":
        reset_state(video_id)
        print("reset done")
    elif action == "set-phase":
        phase = int(sys.argv[3])
        status = sys.argv[4] if len(sys.argv) > 4 else "done"
        artifact = sys.argv[5] if len(sys.argv) > 5 else None
        update_phase(video_id, phase, status, artifact)
        print("updated")
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
