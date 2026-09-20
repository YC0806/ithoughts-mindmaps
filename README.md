# ithoughts-mindmaps — an agent skill for iThoughts mind maps

Let a coding agent read, create, and edit **iThoughts** mind maps (`.itmz`) the
way it edits code: search the tree, open a node, change it, save.

Pure Python 3.8+, **standard library only**. No install, no dependencies, no
network. Works as a skill for any coding agent — not tied to Claude — *and* as
a plain CLI.

```console
$ itmz.py tree 第4章.itmz --depth 1
第4章 系统架构设计
  - 1. 基本定义（重点★★★★★）  (+5)
  - 3. 软件架构的生命周期（非重点☆☆☆☆☆）  (+20)
  - 5. 软件架构风格（超级重点★★★★★）  (+39)
  - 8. 系统质量属性与架构评估（重点★★★★★）  (+69)

$ itmz.py find 第4章.itmz 阶段 --in "8.5.2 ATAM方法"
54369f53  d4  …/8.5.2 ATAM方法/阶段1：场景和需求收集 — 收集场景及约束等需求信息
6c51e916  d4  …/8.5.2 ATAM方法/阶段2：架构视图和场景实现 — 描述架构图，实现场景

$ itmz.py set 第4章.itmz --topic 54369f53 --text "阶段1：场景与需求收集"
saved 第4章.itmz
```

## Why

`.itmz` is a ZIP of XML. You *can* unzip it and hand-edit, and you will get it
wrong: the payload is UTF-8 **with BOM**, every topic carries a `position`
whose coordinate system is undocumented, and the sibling ordering, manifest
counters, and untouched zip members all have to survive the round trip.

This does that correctly, and gives an agent the verbs it actually needs —
`find` by regex or subtree, `show` one node with its context, address nodes by
uuid instead of by retyping long text.

## Install

**As an agent skill** — clone straight into your agent's skills directory
(e.g. `~/.claude/skills/` for Claude Code; other agents have their own):

```bash
git clone https://github.com/<you>/ithoughts-mindmaps ~/.claude/skills/ithoughts-mindmaps
```

The agent picks it up automatically; mention a `.itmz` file and the skill
loads. For a project-local install, clone it into the project's skills
directory instead.

**As a plain CLI** — the script stands alone:

```bash
curl -O https://raw.githubusercontent.com/<you>/ithoughts-mindmaps/main/scripts/itmz.py
chmod +x itmz.py && ./itmz.py --help
```

## Commands

| | |
|---|---|
| `info` | zip members, topic/depth counts, which attributes the map uses |
| `tree` | outline; `--depth` truncates and shows `(+N)` subtree sizes |
| `find` | search by substring or `--re` regex; `--in` a subtree, `--depth`, `--attr` |
| `show` | one topic: every attribute, parent, sibling index, children |
| `export` | whole map (or `--from` a subtree) as markdown or JSON |
| `new` | create an empty map |
| `add` `set` `mv` `rm` | single-topic edits |
| `import` | graft a markdown or JSON outline in; `--replace` a branch, or `--as-root` to build a whole map from one file |
| `relayout` | recompute the tree's coordinates (see Limits for exceptions) |

Writes go in place with a `.bak` alongside, or elsewhere with `-o`.
See [SKILL.md](SKILL.md) for the full reference; editing details and format
internals live in [references/](references/).

### Bulk edits

`itmz.py` is importable, so anything the CLI does not cover is a short script:

```python
import importlib.util, os
spec = importlib.util.spec_from_file_location("itmz", "scripts/itmz.py")
itmz = importlib.util.module_from_spec(spec); spec.loader.exec_module(itmz)

m = itmz.Map("map.itmz")
for t in m.all_topics():                       # bold the label before each colon
    text = t.get("text") or ""
    if "：" in text and "*" not in text:
        pre, sep, rest = text.partition("：")
        t.set("text", "**" + pre + "**" + sep + rest)
        m.touch(t)
m.save(backup=True)                            # keeps iThoughts' own coordinates
```

## The format, briefly

`.itmz` is a ZIP:

| Member | Required | Contents |
|---|---|---|
| `mapdata.xml` | yes | the whole topic tree, UTF-8 **with BOM**, one line |
| `style.xml` | no | per-level fonts, shapes, colors, layout flags |
| `manifest.plist` | no | app id/version, `MapRevision`, topic & note counts |
| `display_state.plist` | no | zoom, viewport, selected uuid |
| `preview.png` | no | thumbnail; iThoughts regenerates it |
| `assets/…` | no | images and attachments |

Everything about a topic lives in **attributes**; nesting is literal XML
nesting. Only `mapdata.xml` and `manifest.plist` are ever rewritten — every
other member is copied through byte for byte, in its original order.

### Coordinates

`position="{x,y}"` is a topic's **center relative to its parent's center**, in
points, `+y` down. Reverse-engineered from maps iThoughts wrote itself:

- font size by depth (per `style.xml`): 32, 20, then 14
- text wraps at 40 half-width units (CJK counts 2)
- `width = 0.5 × fontsize × min(line_units, 40) + 24`
- `line height = 1.2 × fontsize`; box height + sibling gap = `1.2 × fontsize × lines + 22`
- parent→child horizontal gap 19; children stacked and centered on the parent

Replaying this over a 192-topic map iThoughts had laid out reproduces its
coordinates to a **median 4.7pt horizontally and 0pt vertically**.

Since `style.xml` carries `autoAlign="1"`, iThoughts re-runs its own layout on
load, so these are a good starting position rather than the last word. XML
document order is authoritative for sibling order, and `relayout` (on by
default for writes) makes coordinates agree with it. Use `--no-relayout` to
keep a hand-arranged map exactly as it is — the right choice when you are only
changing text.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

50 tests, no dependencies: round-trips, selector precedence, XML escaping and
multi-line text, byte-for-byte preservation of foreign zip members, refusal to
write on an ambiguous selector, and the layout formulas above.

## Limits

- Layout covers the standard right-side tree. Radial maps, `boundary` groups,
  floating topics and callouts keep their stored coordinates — and so do the
  descendants of a folded topic; `relayout` treats it as a leaf.
- `note`, `link`, `icons`, `color`, `task-*` and other optional attributes are
  written and preserved verbatim, but were not verified against every
  iThoughts version — check the result in the app the first time you use one.
- Relationship elements (cross-links between topics) are preserved, not edited.
- `.itmz` is unrelated to XMind's `.xmind`. Different schema; don't cross them.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with or endorsed by toketaware, the makers of iThoughts.
The format notes here are the result of clean-room inspection of files the
application produced.
