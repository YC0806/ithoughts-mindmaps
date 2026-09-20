---
name: ithoughts-mindmaps
description: Read, create, and edit iThoughts mind maps (.itmz files) — inspect the topic tree, add/edit/move/delete topics, import a markdown or JSON outline into a map, export a map back to markdown/JSON, and recompute the visual layout. Use whenever a .itmz file is mentioned, or when asked to build or update an iThoughts / iThoughtsX mind map.
---

# Editing iThoughts (.itmz) mind maps

Use `scripts/itmz.py` (stdlib Python 3, no install) for all reads and writes.
Never hand-edit the XML inside the zip — the script handles the BOM, attribute
escaping, member ordering, manifest counters, and layout coordinates.

`$S` below means the absolute path to `scripts/itmz.py` inside this skill's
directory. Skills can be installed anywhere — `~/.claude/skills/`,
`~/.agents/skills/`, or a project skills dir — so use the base directory the
loader reports for this skill:

```bash
S=<skill-dir>/scripts/itmz.py
python3 "$S" --help
```

## Workflow for a map you have never seen

Do not dump the whole tree into context — a real map runs to hundreds of
topics. Drill down instead:

```bash
python3 "$S" info map.itmz                 # size, depth, which attributes are in use
python3 "$S" tree map.itmz --depth 1       # top-level branches, each with a (+N) subtree count
python3 "$S" tree map.itmz --depth 2 --width 40    # one level further, text truncated
```

`(+N)` tells you where the content mass is, so you know which branch to open.
Then locate the target and act on it **by uuid**, never by retyping long text:

```bash
python3 "$S" find map.itmz 场景 --in "8. 系统质量属性与架构评估"   # uuid + depth + path
python3 "$S" show map.itmz --topic 54369f53                      # every attribute + siblings + children
python3 "$S" set  map.itmz --topic 54369f53 --text "新文字"
python3 "$S" show map.itmz --topic 54369f53                      # confirm
```

Rules of thumb:

- `find` first, `show` to confirm you have the right node, then mutate by uuid
  prefix. Text selectors are fine for unique strings and a trap for common ones.
- For more than a few new topics, write a markdown outline and `import` it —
  far faster and less error-prone than a chain of `add` calls.
- Every in-place save leaves a `.bak` beside the file. Ask the user to close
  the map in iThoughts before you write, and to reopen it afterwards to check.

## Commands

```bash
python3 "$S" info  map.itmz                    # zip members, counts, attributes in use
python3 "$S" tree  map.itmz --ids --depth 2    # outline; --ids prints uuid prefixes
python3 "$S" tree  map.itmz --from "5.1 六大一级架构风格" --width 40

python3 "$S" find  map.itmz 场景               # substring search -> uuid, depth, path
python3 "$S" find  map.itmz "^8\." --re        # regex search
python3 "$S" find  map.itmz --in "8.5 系统架构评估方法" --depth 4   # scope / depth filters
python3 "$S" find  map.itmz --attr note        # every topic carrying a note
python3 "$S" show  map.itmz --topic 54369f53   # attributes, parent, sibling index, children

python3 "$S" export map.itmz --format md       # markdown outline (round-trips)
python3 "$S" export map.itmz --format json     # full attributes, for programmatic edits

python3 "$S" new  map.itmz --title "第9章 测试" --author green

python3 "$S" add  map.itmz --parent ROOT --text "新章节" [--index 0] [--attr note=...]
python3 "$S" set  map.itmz --topic "白盒测试" --text "新文字" --attr 'icons=flag-red'
python3 "$S" set  map.itmz --topic "白盒测试" --attr 'note='        # empty value clears
python3 "$S" mv   map.itmz --topic "判定覆盖" --parent "黑盒测试" [--index 2]
python3 "$S" rm   map.itmz --topic "自顶向下" [--topic ...]

python3 "$S" import   map.itmz outline.md --parent "集成测试" [--replace]
python3 "$S" import   map.itmz outline.md --as-root      # outline's top node becomes the root
python3 "$S" import   map.itmz - --parent ROOT < outline.md
python3 "$S" relayout map.itmz
```

Shared write flags: `-o OUT` (write elsewhere), `--no-backup`,
`--no-relayout` (keep the existing coordinates untouched).

### Selectors

`--topic` / `--parent` accept, in this order: a uuid or unique uuid prefix; a
`/A/B/C` path of topic texts; an exact text; a unique substring. `ROOT` means
the single root topic. An ambiguous selector aborts without writing anything
and lists the candidates — rerun with a uuid prefix from `find`.

### Import format

Markdown headings (`#`, `##`, …) and indented `-`/`*`/`+` bullets mix freely;
a `> ` line becomes the preceding topic's `note`; JSON input is
`[{"text": ..., "note": ..., "children": [...]}]`. The full rules, and a
worked example at `examples/outline.md`, are in
[references/editing.md](references/editing.md) — read it before the first
`import`.

## References

- [references/editing.md](references/editing.md) — import format rules,
  relayout semantics, and the gotchas that only matter when mutating a map
  (radial/folded/floating topics, `preview.png`).
- [references/format.md](references/format.md) — the zip/XML internals, the
  attribute inventory, and the reverse-engineered layout math. Read when
  troubleshooting a map or checking what the script writes.

## Notes

- `.itmz` is unrelated to `.xmind` (XMind's own zip format, different schema).
  Do not point this tool at one.
