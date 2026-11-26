#!/usr/bin/env bash
# Create the GitHub release vX.Y.Z from the built matcher and dataset.
#   scripts/release.sh TAG [--assets DIR] [--sources-file FILE]
# --assets DIR        directory with matcher.json.gz and institutions.parquet
#                     (default: the DVC outputs under artifacts/)
# --sources-file FILE JSON recorded as `sources` in manifest.json (default: the
#                     stage outputs locked in dvc.lock)
# The crosswalk.csv asset (the five identifier columns of the dataset) is
# derived from institutions.parquet, with $PYTHON (default python3), which needs
# pandas and pyarrow.
# DRY_RUN=1 prints the gh command and the generated files, and makes no
# network calls. Run it from a clean checkout of the commit to release.
set -euo pipefail

tag=${1:-}
shift || true
assets_dir=""
sources_file=""
while (($#)); do
  case $1 in
    --assets) assets_dir=${2:?--assets needs a directory}; shift 2 ;;
    --sources-file) sources_file=${2:?--sources-file needs a file}; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "usage: $0 vX.Y.Z [--assets DIR] [--sources-file FILE]" >&2; exit 2; }
version=${tag#v}

run() {
  if [[ -n ${DRY_RUN:-} ]]; then printf '+'; printf ' %q' "$@"; echo; else "$@"; fi
}

pkg_version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n1)
[[ $pkg_version == "$version" ]] || { echo "pyproject.toml version is $pkg_version, not $version." >&2; exit 1; }
normalizer=$(sed -n 's|.*os-normalizer @ git+[^@]*@v\([0-9][^"]*\)".*|\1|p' pyproject.toml | head -n1)
[[ -n $normalizer ]] || { echo "Could not read the os-normalizer pin from pyproject.toml." >&2; exit 1; }

sha=$(git rev-parse HEAD)
if [[ -z ${DRY_RUN:-} ]]; then
  [[ -z $(git status --porcelain --untracked-files=no) ]] || { echo "Working tree has uncommitted changes." >&2; exit 1; }
  git fetch -q origin main
  [[ $sha == "$(git rev-parse origin/main)" ]] || { echo "HEAD is not origin/main; check out the merged commit to release." >&2; exit 1; }
  if gh release view "$tag" >/dev/null 2>&1; then
    echo "Release $tag already exists. Releases are not overwritten; cut a new version." >&2
    exit 1
  fi
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
stage="$work/assets"
mkdir "$stage"

if [[ -n $assets_dir ]]; then
  matcher="$assets_dir/matcher.json.gz"
  dataset="$assets_dir/institutions.parquet"
else
  matcher=artifacts/matcher/matcher.json.gz
  dataset=artifacts/dataset/institutions.parquet
fi
for f in "$matcher" "$dataset"; do
  [[ -f $f ]] || { echo "Missing $f." >&2; exit 1; }
done
cp -L "$matcher" "$stage/matcher.json.gz"
cp -L "$dataset" "$stage/institutions.parquet"
${PYTHON:-python3} -c 'import sys; from pathlib import Path; from os_institutions.loader import to_crosswalk; to_crosswalk(Path(sys.argv[2]), Path(sys.argv[1]))' \
  "$stage/institutions.parquet" "$stage/crosswalk.csv"

if [[ -n $sources_file ]]; then
  jq -e . "$sources_file" >/dev/null || { echo "$sources_file is not valid JSON." >&2; exit 1; }
  cp "$sources_file" "$work/sources.json"
else
  awk '
    /^  [a-z_]+:$/ { stage = $1; sub(/:$/, "", stage) }
    /^    outs:/ { in_outs = 1; next }
    /^    [a-z]+:/ { in_outs = 0 }
    in_outs && /- path:/ { path = $3 }
    in_outs && /md5:/ && path !~ /^metrics\// { print stage, path, $2 }
  ' dvc.lock | jq -Rn '{
    origin: "built by the DVC pipeline in this repository",
    stages: ([inputs | split(" ") | {key: .[0], value: {path: .[1], md5: .[2]}}] | from_entries)
  }' >"$work/sources.json"
fi

for name in matcher.json.gz institutions.parquet crosswalk.csv; do
  jq -n --arg name "$name" --arg sha "$(shasum -a 256 "$stage/$name" | cut -d' ' -f1)" \
    --argjson bytes "$(wc -c <"$stage/$name" | tr -d ' ')" \
    '{($name): {sha256: $sha, bytes: $bytes}}'
done | jq -s 'add' >"$work/assets.json"

jq -n --arg version "$version" --arg git_sha "$sha" --arg normalizer "$normalizer" \
  --slurpfile sources "$work/sources.json" --slurpfile assets "$work/assets.json" \
  '{version: $version, git_sha: $git_sha, normalizer_version: $normalizer,
    sources: $sources[0], assets: $assets[0]}' >"$stage/manifest.json"

(cd "$stage" && shasum -a 256 matcher.json.gz institutions.parquet crosswalk.csv manifest.json >SHA256SUMS)

{
  echo "os-institutions $version: the institutions dataset and the matcher built from it."
  echo
  echo "Commit: \`$sha\`. Lookup keys built with os-normalizer \`$normalizer\`."
  jq -r '.sources.origin // empty | "Origin: " + .' "$stage/manifest.json"
  echo
  echo "| File | Size (bytes) | sha256 |"
  echo "|---|---|---|"
  jq -r '.assets | to_entries[] | "| `\(.key)` | \(.value.bytes) | `\(.value.sha256[0:16])` |"' "$stage/manifest.json"
  echo
  echo "Lineage:"
  echo
  jq -r '(.sources.artifacts // {} | to_entries[] | "- `\(.key)` (\(.value.created_at[0:10]))"),
         (.sources.stages // {} | to_entries[] | "- `\(.key)` `\(.value.md5[0:12])`")' "$stage/manifest.json"
  echo
  echo "Load it with \`os_institutions.load_matcher('$tag')\` and \`os_institutions.load_dataset('$tag')\`."
} >"$work/notes.md"

run gh release create "$tag" "$stage"/matcher.json.gz "$stage"/institutions.parquet "$stage"/crosswalk.csv "$stage"/manifest.json "$stage"/SHA256SUMS \
  --target "$sha" --title "os-institutions $tag" --notes-file "$work/notes.md"

if [[ -n ${DRY_RUN:-} ]]; then
  echo; echo "--- manifest.json ---"; cat "$stage/manifest.json"
  echo; echo "--- SHA256SUMS ---"; cat "$stage/SHA256SUMS"
  echo; echo "--- release notes ---"; cat "$work/notes.md"
fi
