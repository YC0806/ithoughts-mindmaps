#!/usr/bin/env python3
"""itmz.py — read/create/modify iThoughts (.itmz) mind map files.

An .itmz file is a ZIP containing:
  mapdata.xml         (required) UTF-8-BOM XML, the whole topic tree
  style.xml           (optional) map style / theme
  manifest.plist      (optional) app + stats metadata
  display_state.plist (optional) zoom / scroll / selection
  preview.png         (optional) thumbnail
  assets/...          (optional) images and attachments

Only mapdata.xml is edited by this tool; every other member is copied through
byte-for-byte (manifest.plist counters are refreshed).

Stdlib only. Python 3.8+.
"""

import argparse
import copy
import datetime
import json
import math
import os
import re
import shutil
import sys
import uuid as uuidlib
import xml.etree.ElementTree as ET
import zipfile

XML_DECL = '<?xml version="1.0" encoding="utf-8"?>'
MAPDATA = "mapdata.xml"

# ---------------------------------------------------------------- geometry --
# Derived by fitting the coordinates iThoughts itself wrote (see SKILL.md).
# A topic's `position` is the offset of its CENTER from its PARENT's center.
HGAP = 19.0          # horizontal gap between parent box and child box
VPAD = 22.0          # box padding + vertical gap, combined (only sum matters)
VGAP_SHARE = 12.0    # portion of VPAD treated as gap between siblings
BOX_PAD_X = 24.0     # horizontal padding inside a topic box
WRAP_UNITS = 40      # text wraps after this many half-width units
LINE_RATIO = 1.2     # line height = LINE_RATIO * font size
# Font size per depth, mirroring style.xml <level n=...> defaults.
LEVEL_FONT = {0: 32, 1: 20}
DEFAULT_FONT = 14


def visual_len(s):
    """Width of a string in half-width units (CJK/full-width chars count 2)."""
    n = 0
    for ch in s:
        n += 2 if (ord(ch) > 0x2E80 and ch not in "\r\n") else 1
    return n


def font_size(depth):
    return LEVEL_FONT.get(depth, DEFAULT_FONT)


def box_size(text, depth):
    """Estimated (width, height) of a topic box in points."""
    fs = font_size(depth)
    segs = (text or " ").split("\n")
    lines = 0
    widest = 1
    for seg in segs:
        v = max(visual_len(seg), 1)
        lines += max(1, math.ceil(v / WRAP_UNITS))
        widest = max(widest, min(v, WRAP_UNITS))
    w = 0.5 * fs * widest + BOX_PAD_X
    h = LINE_RATIO * fs * lines + (VPAD - VGAP_SHARE)
    return w, h


def fmt_pos(x, y):
    return "{%.2f,%.2f}" % (x, y)


def parse_pos(s):
    m = re.match(r"\{\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\}", s or "")
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


# ------------------------------------------------------------------- model --

class Map:
    """An open .itmz file: parsed mapdata.xml plus the other zip members."""

    def __init__(self, path):
        self.path = path
        self.members = []          # [(name, bytes)] in original order
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                self.members.append((info.filename, z.read(info.filename)))
        raw = dict(self.members).get(MAPDATA)
        if raw is None:
            raise SystemExit("%s: no mapdata.xml (not an .itmz file?)" % path)
        self.root = ET.fromstring(raw.decode("utf-8-sig"))
        self.topics_el = self.root.find("topics")
        if self.topics_el is None:
            raise SystemExit("%s: mapdata.xml has no <topics> element" % path)
        self._parents = {}
        self._reindex()

    # -- tree bookkeeping --------------------------------------------------
    def _reindex(self):
        self._parents = {}
        for parent in self.topics_el.iter("topic"):
            for child in parent.findall("topic"):
                self._parents[child] = parent
        for t in self.topics_el.findall("topic"):
            self._parents.setdefault(t, self.topics_el)

    def roots(self):
        return self.topics_el.findall("topic")

    def all_topics(self):
        return list(self.topics_el.iter("topic"))

    def parent_of(self, el):
        return self._parents.get(el)

    def depth(self, el):
        d = 0
        p = self.parent_of(el)
        while p is not None and p is not self.topics_el:
            d += 1
            p = self.parent_of(p)
        return d

    def path_of(self, el):
        parts = []
        cur = el
        while cur is not None and cur is not self.topics_el:
            parts.append(cur.get("text", ""))
            cur = self.parent_of(cur)
        return "/".join(reversed(parts))

    # -- selection ---------------------------------------------------------
    def find(self, selector):
        """Resolve a selector to exactly one topic.

        Accepted forms:
          <uuid> or a unique uuid prefix
          "/A/B/C"  slash path of topic texts from a root topic
          any substring of a topic's text (must match exactly one topic)
        Prefix with "text:" or "uuid:" or "path:" to force one form.
        """
        if selector in (None, ""):
            raise SystemExit("empty selector")
        kind, _, val = selector.partition(":")
        if kind not in ("uuid", "text", "path"):
            kind, val = "auto", selector

        topics = self.all_topics()
        if kind in ("auto", "uuid"):
            hits = [t for t in topics if (t.get("uuid") or "").startswith(val)]
            if len(hits) == 1:
                return hits[0]
            if kind == "uuid":
                raise SystemExit("uuid selector %r matched %d topics" % (val, len(hits)))

        if kind in ("auto", "path") and "/" in val:
            want = [p for p in val.split("/") if p]
            hits = [t for t in topics
                    if [x for x in self.path_of(t).split("/")][-len(want):] == want]
            if len(hits) == 1:
                return hits[0]
            if kind == "path":
                raise SystemExit("path selector %r matched %d topics" % (val, len(hits)))

        exact = [t for t in topics if t.get("text", "") == val]
        if len(exact) == 1:
            return exact[0]
        sub = [t for t in topics if val in t.get("text", "")]
        if len(sub) == 1:
            return sub[0]
        cands = exact or sub
        if not cands:
            raise SystemExit("selector %r matched no topic" % selector)
        shown = cands[:12]
        more = ("\n  … and %d more; use `find` to list them all"
                % (len(cands) - len(shown))) if len(cands) > len(shown) else ""
        raise SystemExit(
            "selector %r is ambiguous (%d matches; pass a uuid prefix instead):\n%s%s" % (
                selector, len(cands),
                "\n".join("  %s  %s" % ((t.get("uuid") or "")[:8], self.path_of(t))
                          for t in shown), more))

    # -- mutation ----------------------------------------------------------
    def new_topic(self, text, **attrs):
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        el = ET.Element("topic")
        el.set("uuid", str(uuidlib.uuid4()))
        el.set("position", "{0.00,0.00}")
        el.set("text", text)
        for k, v in (("folded", "0"), ("floating", "0"),
                     ("callout", "0"), ("boundary", "0")):
            el.set(k, v)
        el.set("created", now)
        el.set("modified", now)
        for k, v in attrs.items():
            if v is None:
                el.attrib.pop(k, None)
            else:
                el.set(k, str(v))
        return el

    def add(self, parent_el, text, index=None, **attrs):
        el = self.new_topic(text, **attrs)
        kids = parent_el.findall("topic")
        if index is None or index >= len(kids):
            parent_el.append(el)
        else:
            parent_el.insert(list(parent_el).index(kids[max(index, 0)]), el)
        self._reindex()
        return el

    def remove(self, el):
        p = self.parent_of(el)
        if p is None:
            raise SystemExit("cannot remove: topic not in tree")
        p.remove(el)
        self._reindex()

    def move(self, el, new_parent, index=None):
        if el is new_parent or new_parent in el.iter("topic"):
            raise SystemExit("cannot move a topic into itself or its own subtree")
        self.parent_of(el).remove(el)
        kids = new_parent.findall("topic")
        if index is None or index >= len(kids):
            new_parent.append(el)
        else:
            new_parent.insert(list(new_parent).index(kids[max(index, 0)]), el)
        self._reindex()

    def touch(self, el):
        el.set("modified", datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

    # -- layout ------------------------------------------------------------
    def relayout(self):
        """Recompute every `position`, reproducing iThoughts' right-side tree
        layout. Callouts and floating topics keep their coordinates."""
        def laid_out_children(el):
            return [c for c in el.findall("topic")
                    if c.get("callout") != "1" and c.get("floating") != "1"]

        def subtree_height(el, depth):
            own = box_size(el.get("text", ""), depth)[1]
            kids = laid_out_children(el)
            if not kids or el.get("folded") == "1":
                return own
            tot = sum(subtree_height(k, depth + 1) for k in kids) \
                + VGAP_SHARE * (len(kids) - 1)
            return max(own, tot)

        def place(el, depth):
            kids = laid_out_children(el)
            if not kids or el.get("folded") == "1":
                return
            pw = box_size(el.get("text", ""), depth)[0]
            heights = [subtree_height(k, depth + 1) for k in kids]
            total = sum(heights) + VGAP_SHARE * (len(kids) - 1)
            cursor = -total / 2.0
            for k, h in zip(kids, heights):
                cw = box_size(k.get("text", ""), depth + 1)[0]
                k.set("position", fmt_pos(pw / 2 + HGAP + cw / 2, cursor + h / 2))
                cursor += h + VGAP_SHARE
                place(k, depth + 1)

        for r in self.roots():
            r.set("position", "{0.00,0.00}")
            place(r, 0)

    # -- serialization -----------------------------------------------------
    def _mapdata_bytes(self):
        self.root.set("modified", datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
        body = ET.tostring(self.root, encoding="unicode")
        return ("﻿" + XML_DECL + body).encode("utf-8")

    def _manifest_bytes(self, raw):
        try:
            txt = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw
        topics = self.all_topics()
        words = sum(len(re.findall(r"\S+", t.get("text", ""))) for t in topics)
        notes = [t for t in topics if t.get("note")]
        nwords = sum(len(re.findall(r"\S+", t.get("note", ""))) for t in notes)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        repl = {"TopicCount": len(topics), "TopicWordCount": words,
                "NoteCount": len(notes), "NoteWordCount": nwords}
        for key, val in repl.items():
            txt = re.sub(r"(<key>%s</key>\s*<integer>)[^<]*(</integer>)" % key,
                         lambda m, v=val: "%s%d%s" % (m.group(1), v, m.group(2)), txt)
        txt = re.sub(r"(<key>Generated</key>\s*<date>)[^<]*(</date>)",
                     lambda m: "%s%s%s" % (m.group(1), stamp, m.group(2)), txt)
        txt = re.sub(r"(<key>MapRevision</key>\s*<string>)[^<]*(</string>)",
                     lambda m: "%s%s%s" % (m.group(1), uuidlib.uuid4(), m.group(2)), txt)
        return txt.encode("utf-8")

    def save(self, out_path=None, backup=True, drop_preview=False):
        out_path = out_path or self.path
        if backup and os.path.exists(out_path) and os.path.abspath(out_path) == os.path.abspath(self.path):
            shutil.copy2(out_path, out_path + ".bak")
        tmp = out_path + ".tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in self.members:
                if name == MAPDATA:
                    data = self._mapdata_bytes()
                elif name == "manifest.plist":
                    data = self._manifest_bytes(data)
                elif name == "preview.png" and drop_preview:
                    continue
                z.writestr(name, data)
        os.replace(tmp, out_path)
        return out_path


# --------------------------------------------------------------- creation --

MINIMAL_STYLE = (
    '﻿' + XML_DECL +
    '<style name="Default" version="2" mapLayout="1" layoutDensity="1" '
    'topicHugging="1" handDrawnTopics="0" shapeBorder="1" radialLayout="0" '
    'mapViewStyle="0" imagePosition="2" autoAlign="1" level1LinkStyle="5" '
    'level1LinkStyleTapered="0" centerAnchorLink="0" levelNLinkStyle="5" '
    'linkThickness="4" linkAlpha="1" summaryBracketStyle="0" '
    'summaryBracketColor="#FFFF0000" rainbow="0" rainbowClockwise="1" '
    'rainbowAngularDistribution="0" rainbowRange="0" linkColor="#FF073642" '
    'hyperlinkUnderline="1" inheritColor="0" calloutLink="1" calloutShape="0">'
    '<level n="0" topicShape="0" topicColor="#FFFFFFFF" textFontSize="32" gridSpacing="0" />'
    '<level n="1" topicShape="10" textFontSize="20" />'
    '<level n="2" topicShape="0" textFontSize="14" />'
    '<level n="3" /><level n="4" topicShape="3" />'
    '<conditionalFormats /></style>'
)

MANIFEST_TMPL = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" '
    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    '<plist version="1.0">\n  <dict>\n'
    '    <key>Generated</key>\n    <date>{stamp}</date>\n'
    '    <key>AppID</key>\n    <string>com.toketaware.ithoughts.windows</string>\n'
    '    <key>AppVersion</key>\n    <string>6.6.0.0</string>\n'
    '    <key>MapRevision</key>\n    <string>{rev}</string>\n'
    '    <key>TopicCount</key>\n    <integer>1</integer>\n'
    '    <key>TopicWordCount</key>\n    <integer>0</integer>\n'
    '    <key>NoteCount</key>\n    <integer>0</integer>\n'
    '    <key>NoteWordCount</key>\n    <integer>0</integer>\n'
    '  </dict>\n</plist>'
)

DISPLAY_STATE = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" '
    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    '<plist version="1.0">\n  <dict>\n'
    '    <key>zoom</key>\n    <real>1</real>\n'
    '  </dict>\n</plist>'
)


def create_map(path, title, author="", overwrite=False):
    if os.path.exists(path) and not overwrite:
        raise SystemExit("%s already exists (use --force)" % path)
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    root = ET.Element("iThoughts", {
        "version": "4.0", "app": "com.toketaware.ithoughts.windows",
        "app-version": "6.6.0.0", "modified": now, "author": author or "",
    })
    topics = ET.SubElement(root, "topics")
    ET.SubElement(topics, "topic", {
        "uuid": str(uuidlib.uuid4()), "position": "{0.00,0.00}", "text": title,
        "folded": "0", "floating": "0", "callout": "0", "boundary": "0",
        "created": now, "modified": now,
    })
    data = ("﻿" + XML_DECL + ET.tostring(root, encoding="unicode")).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MAPDATA, data)
        z.writestr("style.xml", MINIMAL_STYLE.encode("utf-8"))
        z.writestr("manifest.plist",
                   MANIFEST_TMPL.format(stamp=stamp, rev=uuidlib.uuid4()).encode("utf-8"))
        z.writestr("display_state.plist", DISPLAY_STATE.encode("utf-8"))
    return path


# ------------------------------------------------------------ import/export --

def to_dict(m, el):
    d = dict(el.attrib)
    kids = el.findall("topic")
    if kids:
        d["children"] = [to_dict(m, k) for k in kids]
    return d


def from_dict(m, d, parent_el):
    attrs = {k: v for k, v in d.items() if k not in ("children", "text", "uuid", "position")}
    el = m.add(parent_el, d.get("text", ""), **attrs)
    if d.get("uuid"):
        el.set("uuid", d["uuid"])
    for c in d.get("children", []):
        from_dict(m, c, el)
    return el


def export_markdown(m, el, depth=0, out=None):
    out = out if out is not None else []
    text = (el.get("text") or "").replace("\n", " / ")
    if depth == 0:
        out.append("# " + text)
    else:
        out.append("  " * (depth - 1) + "- " + text)
    note = el.get("note")
    if note:
        pad = "  " * depth
        out.append(pad + "> " + note.replace("\n", "\n" + pad + "> "))
    for c in el.findall("topic"):
        export_markdown(m, c, depth + 1, out)
    return out


def parse_markdown(text):
    """Markdown outline -> nested [{text, children}]. Supports ATX headings
    (#, ##, ...) and indented `-`/`*`/`+` bullets, mixed freely. Tabs and
    every 2 spaces of indent count as one level. `> ` lines become notes."""
    roots = []
    stack = []  # [(level, node)]
    for raw in text.splitlines():
        if not raw.strip():
            continue
        mh = re.match(r"^(#{1,9})\s+(.*)$", raw)
        mb = re.match(r"^([ \t]*)([-*+])\s+(.*)$", raw)
        mn = re.match(r"^[ \t]*>\s?(.*)$", raw)
        if mh:
            level, label = len(mh.group(1)) - 1, mh.group(2).strip()
        elif mb:
            indent = mb.group(1).replace("\t", "  ")
            base = stack[-1][0] + 1 if stack and stack[-1][0] >= 0 else 0
            # heading depth already consumed; bullets nest under last heading
            hlevels = [l for l, n in stack if n.get("_h")]
            level = (max(hlevels) + 1 if hlevels else 0) + len(indent) // 2
            label = mb.group(3).strip()
        elif mn and stack:
            node = stack[-1][1]
            node["note"] = (node.get("note", "") + "\n" + mn.group(1)).strip()
            continue
        else:
            continue
        node = {"text": label, "children": []}
        if mh:
            node["_h"] = True
        while stack and stack[-1][0] >= level:
            stack.pop()
        (stack[-1][1]["children"] if stack else roots).append(node)
        stack.append((level, node))

    def clean(n):
        n.pop("_h", None)
        for c in n["children"]:
            clean(c)
        if not n["children"]:
            n.pop("children")
        return n

    return [clean(n) for n in roots]


# ------------------------------------------------------------------- CLI ----

def flags_of(el):
    tag = ""
    if el.get("callout") == "1":
        tag += " [callout]"
    if el.get("floating") == "1":
        tag += " [floating]"
    if el.get("folded") == "1":
        tag += " [folded]"
    if el.get("note"):
        tag += " [note]"
    if el.get("link"):
        tag += " [link]"
    if el.get("icons"):
        tag += " [icons:%s]" % el.get("icons")
    return tag


def one_line(el, width=None):
    t = (el.get("text") or "").replace("\n", " / ")
    if width and len(t) > width:
        t = t[:width - 1] + "…"
    return t


def print_tree(m, el, depth=0, show_ids=False, max_depth=None, width=None):
    if max_depth is not None and depth > max_depth:
        return
    kids = el.findall("topic")
    hidden = ""
    if max_depth is not None and depth == max_depth and kids:
        hidden = "  (+%d)" % (len(list(el.iter("topic"))) - 1)
    prefix = ("  " * depth) + ("- " if depth else "")
    ident = ("%s  " % (el.get("uuid") or "")[:8]) if show_ids else ""
    print("%s%s%s%s%s" % (ident, prefix, one_line(el, width), flags_of(el), hidden))
    for c in kids:
        print_tree(m, c, depth + 1, show_ids, max_depth, width)


def kv_attrs(pairs):
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        out[k] = None if v == "" else v.replace("\\n", "\n")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="itmz.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_file(p):
        p.add_argument("file")

    def add_write(p):
        p.add_argument("-o", "--output", help="write to this path instead of in place")
        p.add_argument("--no-backup", action="store_true")
        p.add_argument("--no-relayout", action="store_true",
                       help="keep existing positions instead of recomputing")

    p = sub.add_parser("info", help="file structure + map statistics"); add_file(p)
    p = sub.add_parser("tree", help="print the topic outline"); add_file(p)
    p.add_argument("--ids", action="store_true"); p.add_argument("--depth", type=int)
    p.add_argument("--from", dest="start", help="selector for the subtree root")

    p.add_argument("--width", type=int, help="truncate topic text to N chars")

    p = sub.add_parser("find", help="search topics; prints uuid + path"); add_file(p)
    p.add_argument("pattern", nargs="?", default="", help="substring of the topic text")
    p.add_argument("--re", dest="regex", action="store_true", help="treat pattern as a regex")
    p.add_argument("--in", dest="scope", help="only search inside this subtree")
    p.add_argument("--attr", action="append", metavar="K[=V]",
                   help="also require this attribute (optionally equal to V)")
    p.add_argument("--depth", type=int, help="only topics at this depth")
    p.add_argument("--width", type=int, default=70)

    p = sub.add_parser("show", help="all attributes + context of one topic"); add_file(p)
    p.add_argument("--topic", required=True)

    p = sub.add_parser("export", help="dump the map as markdown or json"); add_file(p)
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--from", dest="start")

    p = sub.add_parser("new", help="create a new empty .itmz")
    p.add_argument("file"); p.add_argument("--title", required=True)
    p.add_argument("--author", default=""); p.add_argument("--force", action="store_true")

    p = sub.add_parser("add", help="add a topic under a parent"); add_file(p); add_write(p)
    p.add_argument("--parent", required=True, help="selector; use ROOT for the root topic")
    p.add_argument("--text", required=True)
    p.add_argument("--index", type=int, help="insert position among siblings")
    p.add_argument("--attr", action="append", metavar="K=V")

    p = sub.add_parser("set", help="change attributes of a topic"); add_file(p); add_write(p)
    p.add_argument("--topic", required=True); p.add_argument("--text")
    p.add_argument("--attr", action="append", metavar="K=V",
                   help="e.g. note=..., link=..., icons=flag-red, color=#FFCC0000; K= clears")

    p = sub.add_parser("rm", help="delete a topic and its subtree"); add_file(p); add_write(p)
    p.add_argument("--topic", required=True, action="append")

    p = sub.add_parser("mv", help="move a topic to another parent"); add_file(p); add_write(p)
    p.add_argument("--topic", required=True); p.add_argument("--parent", required=True)
    p.add_argument("--index", type=int)

    p = sub.add_parser("import", help="graft a markdown/json outline into the map")
    add_file(p); add_write(p)
    p.add_argument("source", help="path to .md/.json, or - for stdin")
    p.add_argument("--parent", default="ROOT", help="selector to graft under (default root)")
    p.add_argument("--replace", action="store_true", help="drop the parent's existing children first")
    p.add_argument("--as-root", dest="as_root", action="store_true",
                   help="outline's single top node becomes the root topic itself, "
                        "rather than a child of it (implies --replace)")

    p = sub.add_parser("relayout", help="recompute all positions"); add_file(p); add_write(p)

    a = ap.parse_args(argv)

    # -- read-only commands ------------------------------------------------
    if a.cmd == "new":
        create_map(a.file, a.title, a.author, a.force)
        print("created %s" % a.file)
        return 0

    if a.cmd == "info":
        with zipfile.ZipFile(a.file) as z:
            infos = z.infolist()
        m = Map(a.file)
        print("file: %s" % a.file)
        print("members:")
        for i in infos:
            print("  %-24s %8d bytes" % (i.filename, i.file_size))
        topics = m.all_topics()
        print("iThoughts attrs: %s" % json.dumps(m.root.attrib, ensure_ascii=False))
        print("root topics: %d   topics: %d   max depth: %d"
              % (len(m.roots()), len(topics), max((m.depth(t) for t in topics), default=0)))
        used = sorted({k for t in topics for k in t.attrib})
        print("topic attributes in use: %s" % ", ".join(used))
        extras = [t for t in topics if t.get("note")], [t for t in topics if t.get("link")]
        print("with notes: %d   with links: %d   callouts: %d   floating: %d"
              % (len(extras[0]), len(extras[1]),
                 sum(1 for t in topics if t.get("callout") == "1"),
                 sum(1 for t in topics if t.get("floating") == "1")))
        return 0

    m = Map(a.file)

    def resolve(sel):
        if sel in ("ROOT", "/"):
            rs = m.roots()
            if len(rs) != 1:
                raise SystemExit("ROOT is ambiguous: map has %d root topics" % len(rs))
            return rs[0]
        return m.find(sel)

    if a.cmd == "tree":
        start = [resolve(a.start)] if a.start else m.roots()
        for s in start:
            print_tree(m, s, 0, a.ids, a.depth, a.width)
        return 0

    if a.cmd == "find":
        scope = resolve(a.scope) if a.scope else None
        pool = list(scope.iter("topic")) if scope is not None else m.all_topics()
        if a.regex:
            rx = re.compile(a.pattern)
            pool = [t for t in pool if rx.search(t.get("text", ""))]
        elif a.pattern:
            pool = [t for t in pool if a.pattern in (t.get("text") or "")]
        for spec in a.attr or []:
            k, sep, v = spec.partition("=")
            pool = [t for t in pool
                    if (t.get(k) is not None and (not sep or t.get(k) == v))]
        if a.depth is not None:
            pool = [t for t in pool if m.depth(t) == a.depth]
        for t in pool:
            segs = m.path_of(t).split("/")
            cap = max(12, a.width // 2)
            tail = [s if len(s) <= cap else s[:cap - 1] + "…" for s in segs[-2:]]
            shown = ("…/" if len(segs) > 2 else "") + "/".join(tail)
            print("%s  d%d  %s%s" % ((t.get("uuid") or "")[:8], m.depth(t),
                                     shown, flags_of(t)))
        print("-- %d match%s" % (len(pool), "" if len(pool) == 1 else "es"), file=sys.stderr)
        return 0

    if a.cmd == "show":
        el = resolve(a.topic)
        par = m.parent_of(el)
        sibs = par.findall("topic") if par is not None else []
        print("path     : %s" % m.path_of(el))
        print("depth    : %d" % m.depth(el))
        print("parent   : %s" % (("%s  %s" % ((par.get("uuid") or "")[:8], one_line(par)))
                                 if par is not None and par is not m.topics_el else "(root)"))
        print("sibling  : index %d of %d" % (sibs.index(el) if el in sibs else -1, len(sibs)))
        print("subtree  : %d topics" % len(list(el.iter("topic"))))
        print("attributes:")
        for k, v in el.attrib.items():
            print("  %-10s %s" % (k, v.replace("\n", "\\n")))
        kids = el.findall("topic")
        if kids:
            print("children :")
            for i, c in enumerate(kids):
                print("  [%d] %s  %s%s" % (i, (c.get("uuid") or "")[:8],
                                           one_line(c, 60), flags_of(c)))
        return 0

    if a.cmd == "export":
        start = [resolve(a.start)] if a.start else m.roots()
        if a.format == "json":
            print(json.dumps([to_dict(m, s) for s in start], ensure_ascii=False, indent=2))
        else:
            for s in start:
                print("\n".join(export_markdown(m, s)))
        return 0

    # -- mutating commands -------------------------------------------------
    if a.cmd == "add":
        el = m.add(resolve(a.parent), a.text, index=a.index, **kv_attrs(a.attr))
        print("added %s  %s" % (el.get("uuid"), m.path_of(el)))

    elif a.cmd == "set":
        el = resolve(a.topic)
        if a.text is not None:
            el.set("text", a.text)
        for k, v in kv_attrs(a.attr).items():
            if v is None:
                el.attrib.pop(k, None)
            else:
                el.set(k, v)
        m.touch(el)
        print("updated %s  %s" % (el.get("uuid"), m.path_of(el)))

    elif a.cmd == "rm":
        for sel in a.topic:
            el = resolve(sel)
            path = m.path_of(el)
            n = len(list(el.iter("topic")))
            m.remove(el)
            print("removed %s (%d topics)" % (path, n))

    elif a.cmd == "mv":
        el = resolve(a.topic)
        m.move(el, resolve(a.parent), a.index)
        print("moved -> %s" % m.path_of(el))

    elif a.cmd == "import":
        if a.source == "-":
            raw = sys.stdin.read()
        else:
            with open(a.source, encoding="utf-8-sig") as fh:
                raw = fh.read()
        nodes = json.loads(raw) if a.source.endswith(".json") or raw.lstrip()[:1] in "[{" \
            else parse_markdown(raw)
        if isinstance(nodes, dict):
            nodes = [nodes]
        parent = resolve(a.parent)
        if a.as_root and len(nodes) != 1:
            raise SystemExit("--as-root needs exactly one top-level node, got %d" % len(nodes))
        if a.replace or a.as_root:
            for c in parent.findall("topic"):
                parent.remove(c)
            m._reindex()
        if a.as_root:
            top = nodes[0]
            parent.set("text", top.get("text", parent.get("text", "")))
            for k, v in top.items():
                if k not in ("children", "text", "uuid", "position"):
                    parent.set(k, str(v))
            m.touch(parent)
            for c in top.get("children", []):
                from_dict(m, c, parent)
            print("imported as root: %s (%d children)"
                  % (parent.get("text"), len(parent.findall("topic"))))
        else:
            for n in nodes:
                from_dict(m, n, parent)
            print("imported %d top-level topics under %s" % (len(nodes), m.path_of(parent)))

    elif a.cmd == "relayout":
        pass

    if not getattr(a, "no_relayout", False):
        m.relayout()
    out = m.save(a.output, backup=not a.no_backup)
    print("saved %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
