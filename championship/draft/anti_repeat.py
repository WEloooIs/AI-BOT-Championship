from __future__ import annotations


def same_full_comp(left: list[str], right: list[str]) -> bool:
    return sorted(left) == sorted(right)


def comp_signature(comp: list[str]) -> str:
    return "|".join(sorted(comp))
