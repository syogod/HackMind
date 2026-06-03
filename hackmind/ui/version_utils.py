"""
Helpers for presenting templates by version in pickers.

Shared by the New Project dialog (engagement templates) and the Add Sub-Asset
panel (asset templates): show one entry per template name — the latest version —
unless the user opts into seeing every version.
"""


def parse_version(v: str) -> tuple:
    """
    Parse a version string into a tuple of ints for ordering comparisons.
    Non-numeric segments are treated as 0. e.g. "1.2.3" -> (1, 2, 3).
    """
    parts = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def latest_per_name(templates: list[dict]) -> list[dict]:
    """Return one entry per template name — the one with the highest version."""
    best: dict[str, dict] = {}
    for t in templates:
        name = t["name"]
        if name not in best or parse_version(t["version"]) > parse_version(best[name]["version"]):
            best[name] = t
    return sorted(best.values(), key=lambda t: t["name"].lower())


def group_by_name(templates: list[dict]) -> dict[str, list[dict]]:
    """Group templates by name; within each group sort by version descending."""
    groups: dict[str, list[dict]] = {}
    for t in templates:
        groups.setdefault(t["name"], []).append(t)
    return {
        name: sorted(versions, key=lambda t: parse_version(t["version"]), reverse=True)
        for name, versions in sorted(groups.items(), key=lambda kv: kv[0].lower())
    }
