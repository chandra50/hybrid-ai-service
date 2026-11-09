#!/usr/bin/env bash
# Build a deployable tarball from the latest commit:
#   tools/make_release.sh   ->  dist/hybrid-ai-<date>-<commit>.tar.gz (+ .sha256)
# Only committed files are included (git archive), unpacking to a hybrid-ai/ folder.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "warning: uncommitted changes are NOT included; commit first if you need them" >&2
fi
name="hybrid-ai-$(date +%Y%m%d)-$(git rev-parse --short HEAD)"
mkdir -p dist
git archive --format=tar.gz --prefix=hybrid-ai/ -o "dist/$name.tar.gz" HEAD
(cd dist && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
ls -l "dist/$name.tar.gz"
cat "dist/$name.tar.gz.sha256"
