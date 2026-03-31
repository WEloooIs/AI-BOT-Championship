from __future__ import annotations


def score_match(bot_ids: list[str]) -> list[dict]:
    results = []
    total = len(bot_ids)
    for index, bot_id in enumerate(bot_ids):
        score = float(total - index)
        results.append(
            {
                "bot_id": bot_id,
                "objective_score": score,
                "pressure_score": max(score - 0.5, 0.0),
                "survival_score": score,
                "clutch_score": max(score - 1.0, 0.0),
                "stability_score": score,
                "total_score": score * 5,
            }
        )
    return results
