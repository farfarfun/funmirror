# funmirror

Mirror every repo in a GitHub organization to a Gitee organization, in
parallel, skipping repos whose default branch hasn't changed since the last
run.

Built for [`farfarfun-action/mirror-to-gitee`](https://github.com/farfarfun-action/mirror-to-gitee),
which is a thin wrapper around this package's CLI. It reproduces the core
behavior of [`Yikun/hub-mirror-action`](https://github.com/Yikun/hub-mirror-action)
(clone from GitHub, force-push `refs/remotes/origin/*:refs/heads/*` plus tags
to Gitee) without depending on that action, and adds two things it doesn't
have:

- **Parallelism** — repos are mirrored concurrently via a
  [`funworker`](https://github.com/farfarfun/funworker) pipeline
  (`--workers`, default 8).
- **Skip-if-unchanged** — before cloning anything, the latest commit sha of
  the source and destination default branch is compared; if they already
  match, the repo is skipped entirely.

## Install

```bash
pip install "git+https://github.com/farfarfun/funmirror.git@v0.1.0"
```

## Usage

```bash
funmirror mirror \
  --github-org my-org \
  --gitee-org my-org \
  --gitee-token "$GITEE_TOKEN" \
  --gitee-key-file ~/.ssh/gitee_deploy_key \
  --github-token "$GITHUB_TOKEN" \
  --repo-names repo-a,repo-b \
  --workers 8
```

`--repo-names` is optional; if omitted, every repo in `--github-org` is
mirrored (requires `--github-token` to list them).

Exit code is `1` if any repo failed to mirror; a one-line summary
(`Mirrored X, skipped Y, failed Z (total N)`) is printed and, if
`GITHUB_STEP_SUMMARY` is set, appended to it.

## How a single repo is mirrored

1. Look up the latest commit sha of the source default branch on GitHub.
2. If the repo doesn't exist yet on Gitee, create it; otherwise look up the
   latest commit sha of the same branch on Gitee.
3. If both shas match, skip — nothing to do.
4. Otherwise `git clone` from GitHub, then `git push` (force by default)
   `refs/remotes/origin/*:refs/heads/*` plus tags to Gitee over SSH, with
   retries.

## Development

```bash
pip install -e ".[dev]"
pytest
```
