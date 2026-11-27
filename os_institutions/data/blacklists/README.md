# Institution blacklists

Rows listed here are dropped from the institutions dataset when it is built
(see `build()` in [`dataset.py`](../../dataset.py)). Every `*.csv` in this
folder is loaded, and a dataset row is dropped if its `unitid` (IPEDS) or
`ror_id` matches any row here.

## Columns

| Column | Meaning |
|---|---|
| `unitid` | IPEDS unit ID. Empty for ROR-only rows. |
| `ror_id` | ROR ID. Empty for IPEDS-only rows. |
| `name` | Institution name, for readability only. Not used when building. |
| `control` | IPEDS ownership: `public`, `private nonprofit`, or `private for-profit`. Empty for ROR-only rows. Informational only. |
| `reason` | A reason code from the tables below, or free text for a one-off case. |
| `related` | `branches.csv` and `units.csv` only. The parent or the kept institution it conflicts with. A parent that is not in our dataset is marked `(not in dataset)`. |
| `checked_on` | Date the row was last reviewed. |

Each ID belongs in exactly one file (enforced by `tests/test_blacklist.py`).
When a row fits several files, use the first match in the order below.

## Files and reason codes

| File | `reason` | Meaning |
|---|---|---|
| `documented.csv` | free text | A conflict investigated and explained by hand. |
| `district.csv` | `district` | District, system, or central office record. The individual colleges are kept as separate institutions. |
| `chains.csv` | `chain` | Branch campus of a multi-campus chain. The chain shares its name across many IPEDS rows. |
| `for-profit.csv` | `for-profit` | Private for-profit school that is not part of a chain. |
| `k12.csv` | `k12` | K-12 school (high, primary, or support school). Not higher education. |
| `branches.csv` | `branch` | ROR lists a parent institution. `related` is the parent. |
| `branches.csv` | `shared-domain` | Same web domain as an institution we keep. `related` is one such institution, alphabetically first. |
| `units.csv` | `unit` | Department, centre, institute, or lab that ROR lists as a child of a kept school on the same domain. Only the schools are kept, so a unit's own URL must not claim a path on its parent's site. `related` is the parent. |
| `review.csv` | `no-conflict` | No parent and no shared domain with a kept institution. Candidates for reinstating, still to be reviewed. |

A free-text `reason` is also fine in any file when a row has a one-off explanation
(for example `district.csv` explains the Maricopa System Office as a district office with no ROR link).

## Adding a row

1. Pick the file from the table above.
2. Use that file's reason code, or write free text if the row is unique.
3. Fill in `name` and `checked_on`.
4. If you add a new reason code, add it to the table above and to `CODE_FILES` in
   `tests/test_blacklist.py`.
