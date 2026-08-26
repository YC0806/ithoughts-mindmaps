---
name: itmz
description: Read, create, and edit iThoughts mind maps (.itmz files) — inspect the topic tree, add/edit/move/delete topics, import a markdown or JSON outline into a map, export a map back to markdown/JSON, and recompute the visual layout. Use whenever a .itmz file is mentioned, or when asked to build or update an iThoughts / iThoughtsX mind map.
---

# Editing iThoughts (.itmz) mind maps

Use `scripts/itmz.py` (stdlib Python 3, no install) for all reads and writes.
Never hand-edit the XML inside the zip — the script handles the BOM, attribute
escaping, member ordering, manifest counters, and layout coordinates.

```bash
S=~/.claude/skills/itmz/scripts/itmz.py
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
two spaces (or one tab) of bullet indent is one level. A `> ` line becomes the
preceding topic's `note`. JSON input is `[{"text": ..., "note": ..., "children": [...]}]`
— any other key becomes a topic attribute verbatim.

## The file format

`.itmz` is a plain ZIP. The script rewrites `mapdata.xml`, refreshes
`manifest.plist` counters, and copies every other member through byte-for-byte.

| Member | Required | Contents |
|---|---|---|
| `mapdata.xml` | yes | the entire topic tree |
| `style.xml` | no | theme: per-level fonts, shapes, colors, layout flags |
| `manifest.plist` | no | Apple plist: app id/version, `MapRevision`, topic/note counts |
| `display_state.plist` | no | Apple plist: `zoom`, `visibleRect`, `selected` uuid |
| `preview.png` | no | thumbnail; goes stale after an edit, iThoughts regenerates it on next save |
| `assets/…` | no | embedded images and attachments |

`mapdata.xml` is UTF-8 **with BOM**, written as a single line with no
whitespace between elements:

```xml
<?xml version="1.0" encoding="utf-8"?>
<iThoughts version="4.0" app="com.toketaware.ithoughts.windows" app-version="6.6.0.0"
           modified="2026-08-26T11:19:08" author="green">
  <topics>
    <topic uuid="6266ea99-…" position="{0.00,0.00}" text="第4章 系统架构设计"
           folded="0" floating="0" callout="0" boundary="0"
           created="2026-08-26T10:39:25" modified="2026-08-26T10:39:25">
      <topic uuid="c2d2e86f-…" position="{343.67,-3017.80}" text="1. 基本定义" … />
    </topic>
  </topics>
</iThoughts>
```

Everything lives in `topic` **attributes**; nesting is literal XML nesting, so a
topic's subtree is its element's subtree. Timestamps are local, no timezone
suffix. Newlines inside `text` are XML character references (`&#xA;`), not
literal `\n`.

Attributes present in a plain map: `uuid` (lowercase UUID4), `position`,
`text`, `folded`, `floating`, `callout`, `boundary`, `created`, `modified`.
iThoughts also writes optional ones as needed — `note`, `link`, `icons`,
`color`, `shape`, `summary1`/`summary2`, `task-start`, `task-due`,
`task-priority`, `task-progress`, `task-effort`, `att-name`/`att-id` — and
`<relationship>` elements for cross-links. The script never drops or reorders
an attribute it does not recognize, and `--attr K=V` sets any of them; when
using one that is not already in the file, open the result in iThoughts to
confirm it took effect.

### Coordinates

`position="{x,y}"` is the offset of a topic's **center from its parent's
center**, in points; `+x` is right, `+y` is down. The root is `{0.00,0.00}`.
These were reverse-engineered from a real iThoughts-authored map and the
script's `relayout` reproduces them to a median of ~5pt horizontally and 0pt
vertically:

- font size by depth (from `style.xml`): 32 at depth 0, 20 at depth 1, 14 below
- text wraps after 40 half-width units (CJK counts 2); box width =
  `0.5 × fontsize × min(line_units, 40) + 24`
- line height = `1.2 × fontsize`; box height + sibling gap = `1.2 × fontsize × lines + 22`
- horizontal gap between parent and child boxes: 19
- children are stacked vertically and centered on the parent

Because `style.xml` carries `autoAlign="1"`, iThoughts re-runs its own layout
on load, so these coordinates are a good starting position rather than the
final word. Sibling **document order** in the XML is what the script treats as
authoritative, and `relayout` (on by default for every write) makes the
coordinates agree with it. Pass `--no-relayout` only when preserving a
hand-arranged map matters more than consistency.

## Notes and limits

- The layout engine handles the standard right-side tree. Radial maps,
  `boundary` groups, floating topics, and callouts keep their stored
  coordinates rather than being repositioned.
- `relayout` does not move `callout="1"` or `floating="1"` topics.
- Creating a map with `new` omits `preview.png`; iThoughts shows no thumbnail
  until the file is saved from the app once.
- `.itmz` is unrelated to `.xmind` (XMind's own zip format, different schema).
  Do not point this tool at one.
