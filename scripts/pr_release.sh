#!/usr/bin/env bash
# Publish a PR's local artifacts as a GitHub pre-release `pr-<N>`, or remove it.
#   scripts/pr_release.sh publish [PR]   (PR defaults to the current branch's PR)
#   scripts/pr_release.sh clean [PR]
# DRY_RUN=1 prints the gh commands and makes no network calls.
set -euo pipefail

MAX_BYTES=$((2 * 1024 * 1024 * 1024))
MARKER='<!-- os-institutions:pr-release -->'
ARTIFACTS_DIR=${OS_INSTITUTIONS_ARTIFACTS_DIR:-artifacts}

cmd=${1:-}
pr=${2:-}
[[ $cmd == publish || $cmd == clean ]] || { echo "usage: $0 publish|clean [PR]" >&2; exit 2; }
if [[ -z $pr ]]; then
  pr=$(gh pr view --json number --jq .number)
fi
[[ $pr =~ ^[0-9]+$ ]] || { echo "PR must be a number, got '$pr'" >&2; exit 2; }
tag="pr-$pr"

run() {
  if [[ -n ${DRY_RUN:-} ]]; then printf '+'; printf ' %q' "$@"; echo; else "$@"; fi
}

if [[ $cmd == clean ]]; then
  if [[ -z ${DRY_RUN:-} ]] && ! gh release view "$tag" >/dev/null 2>&1; then
    echo "No release $tag, nothing to clean."
    exit 0
  fi
  run gh release delete "$tag" --cleanup-tag --yes
  exit 0
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
stage="$work/assets"
mkdir "$stage"

# Asset names must be unique and flat: <stage>__<file>, metrics__<stage>.json.
while IFS= read -r f; do
  rel=${f#"$ARTIFACTS_DIR"/}
  ln -s "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" "$stage/${rel//\//__}"
done < <(find "$ARTIFACTS_DIR" -mindepth 2 -maxdepth 2 \( -type f -o -type l \) 2>/dev/null | sort)
for f in metrics/*.json; do
  [[ -e $f ]] && ln -s "$(pwd)/$f" "$stage/metrics__$(basename "$f")"
done
[[ -n $(ls -A "$stage") ]] || { echo "No artifacts under $ARTIFACTS_DIR/ or metrics/." >&2; exit 1; }

for f in "$stage"/*; do
  [[ -e $f ]] || { echo "$(basename "$f") is a dangling symlink (DVC symlinks into the container); use hardlinks, see the README." >&2; exit 1; }
  size=$(wc -c <"$f")
  if ((size > MAX_BYTES)); then
    echo "$(basename "$f") is $size bytes; GitHub release assets are limited to 2 GiB (2147483648 bytes)." >&2
    echo "Remove it from artifacts/ (or split or compress it) and re-run." >&2
    exit 1
  fi
done

(cd "$stage" && shasum -a 256 -- * >"$work/SHA256SUMS")
cp "$work/SHA256SUMS" "$stage/SHA256SUMS"

sha=$(git rev-parse HEAD)
if [[ -z ${DRY_RUN:-} ]]; then
  sha=$(gh pr view "$pr" --json headRefOid --jq .headRefOid)
fi
dirty=""
[[ -n $(git status --porcelain --untracked-files=no) ]] && dirty=" (working tree has uncommitted changes)"

{
  echo "Intermediate artifacts for PR #$pr. Local pipeline outputs, not a release."
  echo
  echo "Commit: \`$sha\`$dirty"
  echo
  echo "| File | Size (bytes) | sha256 |"
  echo "|---|---|---|"
  while read -r hash name; do
    [[ $name == SHA256SUMS ]] && continue
    echo "| \`$name\` | $(wc -c <"$stage/$name" | tr -d ' ') | \`${hash:0:16}\` |"
  done <"$work/SHA256SUMS"
  echo
  echo "Stage outputs as locked in \`dvc.lock\` (md5):"
  echo
  awk '
    /^  [a-z_]+:$/ { stage = $1; sub(/:$/, "", stage) }
    /^    outs:/ { in_outs = 1; next }
    /^    [a-z]+:/ { in_outs = 0 }
    in_outs && /- path:/ { path = $3 }
    in_outs && /md5:/ && path !~ /^metrics\// { print "- `" stage "`: `" path "` `" $2 "`" }
  ' dvc.lock
} >"$work/notes.md"

title="PR #$pr artifacts"
if [[ -n ${DRY_RUN:-} ]]; then
  exists=""
else
  exists=$(gh release view "$tag" --json tagName --jq .tagName 2>/dev/null || true)
fi

if [[ -n $exists ]]; then
  run gh release edit "$tag" --prerelease --title "$title" --notes-file "$work/notes.md"
  run gh release upload "$tag" "$stage"/* --clobber
  # Drop assets from an earlier publish that no longer exist locally.
  for name in $(gh release view "$tag" --json assets --jq '.assets[].name'); do
    [[ -e $stage/$name ]] || run gh release delete-asset "$tag" "$name" --yes
  done
else
  run gh release create "$tag" "$stage"/* --prerelease --target "$sha" --title "$title" --notes-file "$work/notes.md"
fi

repo_url="<repo url>"
[[ -n ${DRY_RUN:-} ]] || repo_url=$(gh repo view --json url --jq .url)
release_url="$repo_url/releases/tag/$tag"
{
  echo "$MARKER"
  echo "**Artifacts:** [\`$tag\`]($release_url) at \`${sha:0:7}\`"
  echo
  echo "| Stage | Metrics |"
  echo "|---|---|"
  for f in metrics/*.json; do
    [[ -e $f ]] || continue
    echo "| \`$(basename "$f" .json)\` | $(jq -r 'to_entries | map("\(.key) \(.value)") | join(", ")' "$f") |"
  done
} >"$work/comment.md"

comment_id=""
if [[ -z ${DRY_RUN:-} ]]; then
  comment_id=$(gh api "repos/{owner}/{repo}/issues/$pr/comments" --paginate \
    --jq "[.[] | select(.body | contains(\"$MARKER\")) | .id] | first // empty")
fi
if [[ -n $comment_id ]]; then
  run gh api -X PATCH "repos/{owner}/{repo}/issues/comments/$comment_id" -F "body=@$work/comment.md"
else
  run gh pr comment "$pr" --body-file "$work/comment.md"
fi

if [[ -n ${DRY_RUN:-} ]]; then
  echo; echo "--- release notes ---"; cat "$work/notes.md"
  echo; echo "--- PR comment ---"; cat "$work/comment.md"
fi
