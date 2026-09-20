# The .itmz file format

Internals, for troubleshooting a wrong-looking map, investigating coordinates,
or reviewing anything that bypasses `scripts/itmz.py`. The workflow and
commands in [../SKILL.md](../SKILL.md) are enough for everyday use — read
this only when you need to know what is inside the file.

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
suffix. Newlines inside `text` are XML character references (`&#10;`), not
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

## Coordinates

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
final word.
