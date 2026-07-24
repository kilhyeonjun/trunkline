#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

required=(LICENSE README.md SECURITY.md CONTRIBUTING.md THIRD_PARTY_NOTICES.md)
for file in "${required[@]}"; do
  if [ ! -f "$file" ]; then
    echo "public audit: missing $file" >&2
    exit 1
  fi
done

private_paths_pattern='^(\.superpowers/|docs/superpowers/|telegram-plugin/)'
if git ls-files | grep -Eq "$private_paths_pattern"; then
  echo "public audit: private path is tracked" >&2
  git ls-files | grep -E "$private_paths_pattern" >&2
  exit 1
fi

patterns=(
  "/Users/"
  "hyeonjun@""gameduo"
  "gameduo"".net"
  "BEGIN PRIVATE KEY"
  "BEGIN OPENSSH PRIVATE KEY"
  "ghp""_"
  "github_pat""_"
  "xoxb""-"
  "xoxp""-"
)

for pattern in "${patterns[@]}"; do
  if git grep -n -I -F "$pattern" -- . \
      ':(exclude)scripts/audit-public-tree.sh' \
      ':(exclude)tests/test_public_audit.py'; then
    echo "public audit: sensitive pattern found" >&2
    exit 1
  fi
done

grep -Fq 'license = { file = "LICENSE" }' pyproject.toml || {
  echo "public audit: MIT license metadata missing" >&2
  exit 1
}
grep -Fq 'trunkline = "trunkline.cli:main"' pyproject.toml || {
  echo "public audit: console script metadata missing" >&2
  exit 1
}

echo "public audit: PASS"
