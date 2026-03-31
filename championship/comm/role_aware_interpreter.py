from __future__ import annotations


def interpret_signal(role: str, signal: str) -> dict[str, float]:
    weights = {"pressure": 0.0, "support": 0.0, "retreat": 0.0}
    if signal.startswith("push"):
        weights["pressure"] = 1.0 if role in ("aggro", "flex") else 0.5
    if signal in ("need_help", "group_up"):
        weights["support"] = 1.0 if role in ("support", "objective") else 0.4
    if signal in ("fall_back", "reset", "defend_goal"):
        weights["retreat"] = 1.0 if role in ("anchor", "support") else 0.6
    return weights
