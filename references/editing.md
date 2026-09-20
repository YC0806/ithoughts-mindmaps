# Editing: import, relayout, and write gotchas

Details that only matter when creating or mutating a map. SKILL.md carries
the command cheat sheet, the selector rules, and the safety rules (`.bak`
files, asking the user to close the map) — read this before the first
substantial `import` or when a write behaves unexpectedly.

## Import format

Markdown headings (`#`, `##`, …) and indented `-`/`*`/`+` bullets mix freely;
two spaces (or one tab) of bullet indent is one level. A `> ` line becomes the
preceding topic's `note`. JSON input is `[{"text": ..., "note": ..., "children": [...]}]`
— any other key becomes a topic attribute verbatim. A worked example ships
with the skill at `examples/outline.md`.

## Relayout

Every write recomputes the tree's coordinates by default, so the coordinates
agree with sibling **document order** — the order the script (and iThoughts)
treats as authoritative. Pass `--no-relayout` only when preserving a
hand-arranged map matters more than consistency. The coordinate math itself —
what `position="{x,y}"` means and the sizing formulas — is documented in
[format.md](format.md).

## Write gotchas

- The layout engine handles the standard right-side tree. Radial maps,
  `boundary` groups, floating topics, and callouts keep their stored
  coordinates rather than being repositioned.
- `relayout` does not move `callout="1"` or `floating="1"` topics, nor the
  descendants of a `folded="1"` topic — a folded topic is laid out as a leaf.
  Unfold it first (`set --attr folded=0`) to reposition a folded subtree.
- Creating a map with `new` omits `preview.png`; iThoughts shows no thumbnail
  until the file is saved from the app once.
