#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_URL="${REMOTE_URL:-https://github.com/Kman182401/business-agent.git}"
BRANCH_NAME="${BRANCH_NAME:-main}"
COMMIT_MESSAGE=${1:-}

cd "$ROOT_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "[sync] git is not installed. Please install git first." >&2
  exit 1
fi

if [ ! -d .git ]; then
  echo "[sync] Initialising git repository in $ROOT_DIR"
  git init
  git symbolic-ref HEAD "refs/heads/$BRANCH_NAME"
fi

current_branch="$(git symbolic-ref --short HEAD)"
if [ "$current_branch" != "$BRANCH_NAME" ]; then
  echo "[sync] Switching to branch $BRANCH_NAME"
  git checkout -B "$BRANCH_NAME"
fi

if git remote | grep -qx origin; then
  current_url="$(git remote get-url origin)"
  if [ "$current_url" != "$REMOTE_URL" ]; then
    echo "[sync] Updating origin URL $current_url -> $REMOTE_URL"
    git remote set-url origin "$REMOTE_URL"
  fi
else
  echo "[sync] Adding origin remote $REMOTE_URL"
  git remote add origin "$REMOTE_URL"
fi

if [ -z "$COMMIT_MESSAGE" ]; then
  COMMIT_MESSAGE="Sync $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
fi

# Stage all modifications, deletions, and new files
git add -A

if git diff --cached --quiet; then
  echo "[sync] No changes detected; nothing to commit."
else
  echo "[sync] Committing changes with message: $COMMIT_MESSAGE"
  git commit -m "$COMMIT_MESSAGE"
fi

echo "[sync] Pushing to origin/$BRANCH_NAME"
git push origin "$BRANCH_NAME"
