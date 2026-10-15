# Changelog

## 0.6.1

### 变更（破坏性：声明的 Python 下限收窄）

- `requires-python` 从 `>=3.9` 改为 `>=3.10`，`funworker` 下限从 `>=0.0.1`
  抬到 `>=0.1.1`。原来这两条声明互相矛盾，3.9 从来就跑不起来：
  `src/funmirror/sync/org_sync.py` import 的 `BaseConsumer` /
  `BaseProcessor` / `BaseProducer` / `Pipeline` 最早由 funworker 0.1.1 提供，
  而 0.1.1 及之后每个版本都声明 `requires-python >=3.10`——3.9 上装不到任何
  可用的 funworker。解析器于是回落到 funworker 0.0.1，而那个 wheel 里根本
  没有 `funworker` 包（只有一个 `funapi/`），`import funworker` 直接
  ModuleNotFoundError。
- **迁移**：3.9 用户需升级到 3.10 及以上。本次只让声明与既有依赖事实对齐，
  没有任何代码行为变化（funmirror 自身源码不含 3.10+ 语法）。3.9 上的安装
  现在会在依赖解析期给出明确的版本冲突报错，而不是装完之后再在 import 时炸。

## 0.6.0

Full syncs were spending nearly all of their wall clock waiting, not working.
Measured on a 139-repo org: 164s of a 173s run went on the detect phase, and
almost none of it on anything useful.

- Read Gitee branch heads with `git ls-remote` instead of
  `GET /repos/{org}/{repo}/branches/{branch}`. Every Gitee REST call is
  serialized behind a 0.5s minimum interval to stay clear of the API's WAF, and
  a full sync needs exactly one head per repo -- so 139 repos cost ~140s of
  pure waiting. The git transport answers the same question without that limit,
  eight lookups at a time.
- Resolve `--repo-names` from a single org listing rather than one
  `default_branch` call per name. That loop was sequential and ran before the
  pipeline started, on incremental runs too: ~20s for 139 names, now two calls.
  Names the listing doesn't cover are still asked about individually.
- Don't let a ref lookup block on a prompt nobody can answer. `BatchMode=yes`
  for ssh, no credential helper, and any inherited `GIT_ASKPASS` dropped --
  an editor's helper was observed hanging a single lookup for two full minutes
  while holding one of the eight slots.
- `git_env()` returns nothing when no SSH key is configured. It used to build
  `ssh -i  -o StrictHostKeyChecking=no ...`, where `-i` eats the `-o` after it
  and the option quietly goes missing.

## 0.5.1

- Have the release pass log a line even when nothing moved, so a clean run
  doesn't read exactly like one that never happened.

## 0.5.0

- Mirror releases and their attached files (`--sync-releases`).
- Migrate the `funmirror` command-line interface from argparse to Typer while
  retaining the `mirror` command and its existing options.
