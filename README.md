# funmirror

Mirror every repo from one hosting platform's organization to another's, in
parallel, skipping repos whose default branch hasn't changed since the last
run. Supports GitHub, Gitee, GitLab and GitCode as either source or
destination.

Built for [`farfarfun-action/mirror-repo`](https://github.com/farfarfun-action/mirror-repo),
which is a thin wrapper around this package's CLI. It reproduces the core
behavior of [`Yikun/hub-mirror-action`](https://github.com/Yikun/hub-mirror-action)
(clone from the source platform, force-push `refs/remotes/origin/*:refs/heads/*`
plus tags to the destination) without depending on that action, and adds two
things it doesn't have:

- **Parallelism** — repos are mirrored concurrently via a
  [`funworker`](https://github.com/farfarfun/funworker) pipeline
  (`--workers`, default 8).
- **Skip-if-unchanged** — before cloning anything, the latest commit sha of
  the source and destination default branch is compared; if they already
  match, the repo is skipped entirely.

## Install

```bash
pip install "git+https://github.com/farfarfun/funmirror.git@v0.2.0"
```

## Usage

```bash
funmirror mirror \
  --src-platform github --dst-platform gitee \
  --src-org my-org --dst-org my-org \
  --dst-token "$GITEE_TOKEN" \
  --dst-key-file ~/.ssh/gitee_deploy_key \
  --src-token "$GITHUB_TOKEN" \
  --repo-names repo-a,repo-b \
  --workers 8
```

`--src-platform`/`--dst-platform` are one of `github`, `gitee`, `gitlab`,
`gitcode`. `--src-key-file`/`--dst-key-file` (SSH key for push) are only
required when the corresponding platform is `gitee`. `--src-endpoint`/
`--dst-endpoint` are only used for self-hosted GitLab instances.
`--repo-names` is optional; if omitted, every repo in `--src-org` is
mirrored (requires `--src-token` to list them).

Exit code is `1` if any repo failed to mirror; a one-line summary
(`Mirrored X, skipped Y, failed Z (total N)`) is printed and, if
`GITHUB_STEP_SUMMARY` is set, appended to it.

## How a single repo is mirrored

1. Look up the latest commit sha of the source default branch.
2. If the repo doesn't exist yet on the destination, create it; otherwise
   look up the latest commit sha of the same branch there.
3. If both shas match, skip — nothing to do.
4. Otherwise `git clone` from the source, then `git push` (force by default)
   `refs/remotes/origin/*:refs/heads/*` plus tags to the destination, with
   retries.

## Development

```bash
pip install -e ".[dev]"
pytest
```
