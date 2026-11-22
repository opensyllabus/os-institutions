"""Compare two matchers on a private sample and write aggregates only.

Nothing from the sample itself (URLs, e-mails, school names) is written, only
per-institution counts and totals.
"""

import json
from pathlib import Path

import pandas as pd
import typer
from loguru import logger
from tqdm import tqdm

from os_institutions.matcher import load_model, model_path
from os_institutions.matcher.validate import (
    institutions_table,
    match_institution,
    read_input,
)
from os_institutions.paths import artifacts_dir

TOP = 10

app = typer.Typer()


def identity(institution):
    """Key of an institution that is stable across matcher builds (`_id` is
    only a row index)."""
    if institution is None:
        return None
    for field in ("ror_id", "wikidata_id", "grid_id"):
        if value := getattr(institution, field):
            return f"{field}:{value}"
    if institution.unitid is not None and pd.notna(institution.unitid):
        return f"unitid:{institution.unitid}"
    return f"name:{institution.name}"


def match_all(model, df):
    tqdm.pandas()
    return df.progress_apply(lambda x: match_institution(model, x), axis=1)


def side(keys, counts):
    matched = keys.notna()
    total = int(counts.sum())
    return {
        "matched_rows": int(matched.sum()),
        "matched_count": int(counts[matched].sum()),
        "match_rate": round(int(counts[matched].sum()) / total, 5)
        if total
        else None,
        "institutions": int(keys.nunique()),
    }


def top_changed(tally_old, tally_new, names):
    both = pd.concat(
        [tally_old.rename("old"), tally_new.rename("new")], axis=1
    ).fillna(0)
    both["delta"] = both["new"] - both["old"]
    both = both[both["delta"] != 0]
    both = both.reindex(both["delta"].abs().sort_values(ascending=False).index)
    return [
        {"institution": names[key], "old": int(row.old), "new": int(row.new)}
        for key, row in both.head(TOP).iterrows()
    ]


def top_of(tally, keys, names):
    tally = tally[tally.index.isin(keys)].sort_values(ascending=False)
    return [
        {"institution": names[key], "count": int(count)}
        for key, count in tally.head(TOP).items()
    ]


def summarize(counts, new, old=None):
    """Aggregate summary of matching a sample with `new` (and `old`).

    `counts` is the sample's count column; `new` and `old` are aligned
    Series of the Institution (or None) each sample row matched.
    """
    summary = {
        "sample": {"rows": len(counts), "count": int(counts.sum())},
        "new": None,
        "old": None,
    }
    names = {
        identity(i): i.name
        for s in (new, old)
        if s is not None
        for i in s
        if i
    }

    new_keys = new.map(identity)
    summary["new"] = side(new_keys, counts)
    if old is None:
        return summary

    old_keys = old.map(identity)
    summary["old"] = side(old_keys, counts)

    changed = old_keys.fillna("") != new_keys.fillna("")
    summary["changed"] = {
        "rows": int(changed.sum()),
        "count": int(counts[changed].sum()),
        "newly_matched_count": int(counts[changed & old_keys.isna()].sum()),
        "no_longer_matched_count": int(
            counts[changed & new_keys.isna()].sum()
        ),
        "reassigned_count": int(
            counts[changed & old_keys.notna() & new_keys.notna()].sum()
        ),
    }

    tally_old = counts.groupby(old_keys).sum()
    tally_new = counts.groupby(new_keys).sum()
    gained = tally_new.index.difference(tally_old.index)
    lost = tally_old.index.difference(tally_new.index)
    summary["gained_institutions"] = len(gained)
    summary["lost_institutions"] = len(lost)
    summary["top_gained"] = top_of(tally_new, gained, names)
    summary["top_lost"] = top_of(tally_old, lost, names)
    summary["top_changed"] = top_changed(tally_old, tally_new, names)
    return summary


def pct(x):
    return "n/a" if x is None else f"{x * 100:.2f}%"


def table(rows, header):
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def render(summary):
    sample, new, old = summary["sample"], summary["new"], summary["old"]
    lines = [
        f"Sample: {sample['rows']:,} rows, count {sample['count']:,}.",
        "",
    ]
    if old is None:
        lines += [
            "No baseline release yet, so only the new matcher is shown.",
            "",
        ]
        lines += table(
            [
                ["Match rate (by count)", pct(new["match_rate"])],
                ["Matched rows", f"{new['matched_rows']:,}"],
                ["Institutions matched", f"{new['institutions']:,}"],
            ],
            ["", "new"],
        )
        return "\n".join(lines) + "\n"

    changed = summary["changed"]
    lines += table(
        [
            [
                "Match rate (by count)",
                pct(old["match_rate"]),
                pct(new["match_rate"]),
            ],
            [
                "Matched rows",
                f"{old['matched_rows']:,}",
                f"{new['matched_rows']:,}",
            ],
            [
                "Institutions matched",
                f"{old['institutions']:,}",
                f"{new['institutions']:,}",
            ],
        ],
        ["", "old", "new"],
    )
    lines += [
        "",
        f"Rows matched differently: {changed['rows']:,} "
        f"(count {changed['count']:,}): "
        f"{changed['newly_matched_count']:,} newly matched, "
        f"{changed['no_longer_matched_count']:,} no longer matched, "
        f"{changed['reassigned_count']:,} reassigned.",
        f"Institutions gained: {summary['gained_institutions']:,}, "
        f"lost: {summary['lost_institutions']:,}.",
    ]
    for title, key, header in (
        (
            "Largest count changes",
            "top_changed",
            ["Institution", "old", "new"],
        ),
        ("Top institutions gained", "top_gained", ["Institution", "count"]),
        ("Top institutions lost", "top_lost", ["Institution", "count"]),
    ):
        if summary[key]:
            rows = [list(r.values()) for r in summary[key]]
            lines += ["", f"**{title}**", ""] + table(rows, header)
    return "\n".join(lines) + "\n"


@app.command()
def main(
    path: Path = typer.Option(
        ...,
        help="Local parquet (file or directory) or CSV of institution inputs "
        "with url, source_url, email, school_name, and count columns.",
    ),
    new: Path | None = typer.Option(
        None, help="Matcher to evaluate (default: the matcher output)."
    ),
    old: Path | None = typer.Option(
        None, help="Baseline matcher; omit when there is no baseline yet."
    ),
    output_dir: Path | None = typer.Option(
        None,
        help="Where to write summary.json, summary.md and validation.csv "
        "(default: the validation directory).",
    ),
):
    output_dir = output_dir or artifacts_dir() / "validation"
    df = read_input(path)
    counts = df["count"]

    logger.info(f"Matching {len(df)} rows with the new matcher")
    new_matches = match_all(load_model(new or model_path()), df)
    old_matches = None
    if old:
        logger.info(f"Matching {len(df)} rows with the old matcher")
        old_matches = match_all(load_model(old), df)

    summary = summarize(counts, new_matches, old_matches)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    (output_dir / "summary.md").write_text(render(summary))
    institutions_table(df.assign(institution=new_matches)).to_csv(
        output_dir / "validation.csv", index=False
    )
    logger.info(f"Wrote the comparison to {output_dir}")


if __name__ == "__main__":
    app()
