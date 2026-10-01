"""Perception from the DOM instead of from pixels.

Replaces: screencapture -> Apple Vision OCR -> merge blocks -> reading order.
With:      one Runtime.evaluate that returns the element list already ordered.

The trade is explicit. OCR sees anything painted, including canvases and text
baked into images. The DOM sees only real elements — but it sees them *exactly*:
correct text, correct role, correct label, and a click point in viewport
coordinates, which is what CDP Input wants. The original had to convert Retina
capture pixels back into screen points.

Each collected element is stamped with `data-tscu="<index>"` so later steps have
a stable handle to click, focus and scroll. Stamps from the previous snapshot are
cleared first, so an element that vanished cannot be clicked by mistake.

What a user has typed is never read. An input's current value is not collected,
and no element takes its name from it, so a password, a one-time code or a card
number cannot reach the classifier, the writer, the log or the run folder. The
only value used is a button input's, which is the button's own label. Fields
that ask for a credential are marked `secret`, and nothing is typed into them.

The same script collects the page's visible text, the prices, dates and error
messages that are not controls, as `page_text` blocks kept apart from the element
list, so a block is never a click target. The rule above holds there too: text in
a text control or an editable region, such as an unsent `contenteditable` draft,
is not collected.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

VISIBLE_RECT_JS = r"""
function visibleRect(el) {
  const r = el.getBoundingClientRect();
  let left=Math.max(0,r.left), top=Math.max(0,r.top), right=Math.min(innerWidth,r.right), bottom=Math.min(innerHeight,r.bottom);
  for (let p=el.parentElement; p; p=p.parentElement) {
    const style=getComputedStyle(p), box=p.getBoundingClientRect();
    if (["auto","scroll","hidden","clip"].includes(style.overflowX)) {
      left=Math.max(left,box.left+p.clientLeft); right=Math.min(right,box.left+p.clientLeft+p.clientWidth);
    }
    if (["auto","scroll","hidden","clip"].includes(style.overflowY)) {
      top=Math.max(top,box.top+p.clientTop); bottom=Math.min(bottom,box.top+p.clientTop+p.clientHeight);
    }
  }
  return right-left>=2 && bottom-top>=2 ? {left,top,right,bottom,width:right-left,height:bottom-top} : null;
}
"""

INTERACTIVE_JS = r"""
(() => {
  __VISIBLE_RECT_HELPER__
  function renderedText(root) {
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT), range=document.createRange();
    let text='';
    for (let node; (node=walker.nextNode()) && text.length<240;) {
      const parent=node.parentElement;
      if (!node.nodeValue.trim() || parent.closest('select,textarea,input,script,style,[aria-hidden="true"],[contenteditable]:not([contenteditable="false"]),[role="textbox"]')) continue;
      const style=getComputedStyle(parent), clip=visibleRect(parent);
      if (!clip || style.visibility==='hidden' || Number(style.opacity)===0 || parseFloat(style.fontSize)===0) continue;
      range.selectNodeContents(node);
      if (!Array.from(range.getClientRects()).some(r=>r.right>clip.left && r.left<clip.right && r.bottom>clip.top && r.top<clip.bottom)) continue;
      text+=' '+node.nodeValue;
    }
    return text.replace(/\s+/g,' ').trim();
  }
  document.querySelectorAll("[data-tscu]").forEach(el => el.removeAttribute("data-tscu"));
  const ROLES = new Set(["button","link","menuitem","menuitemcheckbox","menuitemradio",
                         "tab","checkbox","radio","switch","combobox","option","searchbox",
                         "textbox","slider","spinbutton"]);
  const TAGS = new Set(["A","BUTTON","INPUT","SELECT","TEXTAREA","SUMMARY","OPTION","LABEL"]);
  const SEL = "a,button,input,select,textarea,summary,label,[role],[onclick],[tabindex],div,section,article,main,span,img,canvas,li,[draggable],svg circle,svg rect,svg polygon,svg path,svg ellipse";
  // Inputs that take free text. Everything else (checkbox, radio, file, range...) is clicked.
  const TEXT_TYPES = new Set(["text","search","email","url","tel","number","password"]);
  // An input of these types shows its value as its label, and the page wrote that value.
  const BUTTON_TYPES = new Set(["submit","button","reset"]);
  // Autocomplete tokens for credentials and payment data (WHATWG autofill field names).
  const SECRET_AUTOCOMPLETE = /(^|\s)(current-password|new-password|one-time-code|cc-number|cc-csc|cc-exp|cc-exp-month|cc-exp-year)(\s|$)/;
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = [];
  const nodes = [];
  const seen = new Set();
  const knownControls = window.__tscuKnownControls ||= new WeakSet();
  let sid = 0, belowFold = 0, total = 0;
  for (const el of document.querySelectorAll(SEL)) {
    total++;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    // Viewport test BEFORE any style resolution. On a heavy page most candidates
    // are off-screen, and getComputedStyle is the expensive call in this loop —
    // skipping it for the ones we would discard anyway is the whole optimisation.
    const onScreen = r.top < vh && r.bottom > 0 && r.left < vw && r.right > 0;
    if (!onScreen) { belowFold++; continue; }
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || st.display === "none" || parseFloat(st.opacity || "1") === 0) continue;
    if (el.disabled || el.getAttribute("aria-hidden") === "true") continue;
    // Styled checkboxes/radios often hide the native input but keep its label
    // visible and clickable. Expose that real click target with the input state.
    const labelControl = el.tagName === "LABEL" ? el.control : null;
    if (el.tagName === "LABEL" && (!labelControl || !["radio","checkbox"].includes(labelControl.type) || labelControl.disabled)) continue;
    const role = (el.getAttribute("role") || labelControl?.type || (el.classList.contains("ui-slider-handle") ? "slider" : (el.classList.contains("ui-autocomplete-input") || el.hasAttribute("list") || ["list","both"].includes(el.getAttribute("aria-autocomplete"))) ? "combobox" : "")).toLowerCase();
    const scrollable = el.scrollHeight > el.clientHeight + 4 && ["auto","scroll"].includes(st.overflowY);
    const imageControl = st.content.startsWith('url(');
    const visual = imageControl || (el.children.length === 0 && !el.textContent.trim() && r.width >= 8 && r.height >= 8 &&
      (st.backgroundColor !== "rgba(0, 0, 0, 0)" || ["IMG","CANVAS"].includes(el.tagName)));
    const draggable = el.draggable || el.classList.contains("ui-sortable-handle") || el.classList.contains("ui-draggable") || ["grab","move"].includes(st.cursor);
    const shape = el.namespaceURI === "http://www.w3.org/2000/svg" && ["circle","rect","polygon","path","ellipse"].includes(el.tagName.toLowerCase());
    const previouslyInteractive = knownControls.has(el);
    const pointer = st.cursor === "pointer" && (!el.parentElement || getComputedStyle(el.parentElement).cursor !== "pointer" || el.children.length === 0);
    if (!(TAGS.has(el.tagName) || ROLES.has(role) || el.hasAttribute("onclick") || el.hasAttribute("tabindex") || scrollable || visual || pointer || draggable || shape || previouslyInteractive)) continue;
    // Decorative descendants inherit pointer cursors and duplicate their button.
    // Keep independently interactive children, but let semantic parents own icons
    // and labels so dense calendars do not crowd footer controls out of the budget.
    const independent = TAGS.has(el.tagName) || ROLES.has(role) || el.hasAttribute("onclick") || el.hasAttribute("tabindex") || scrollable || draggable;
    const owner = el.parentElement?.closest('a,button,summary,label,[role="button"],[role="link"],[role="option"],[role="checkbox"],[role="radio"],[role="tab"]');
    if (!independent && owner) continue;
    if (role === "gridcell" && el.querySelector('button,[role="button"]')) continue;
    if (pointer) knownControls.add(el);
    const type = el.tagName === "INPUT" ? String(el.type || "text").toLowerCase() : "";
    const secret = type === "password" ||
      SECRET_AUTOCOMPLETE.test((el.getAttribute("autocomplete") || "").toLowerCase());
    const field = el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && TEXT_TYPES.has(type));
    const labelledBy = (el.getAttribute("aria-labelledby") || "").split(/\s+/)
      .filter(Boolean).map(id => document.getElementById(id)?.textContent || "").join(" ");
    let name = (el.getAttribute("aria-label") || labelledBy || el.getAttribute("placeholder") || "").trim();
    if (!name && el.labels) name = Array.from(el.labels).map(label => {
      const copy = label.cloneNode(true);
      copy.querySelectorAll('input,textarea,[contenteditable]').forEach(node => node.remove());
      return copy.textContent || "";
    }).join(" ");
    // Never a text control's value or its own text: that is what the user typed.
    const typedInto = field || el.isContentEditable || role === "textbox" || role === "searchbox";
    // Calendar buttons commonly expose their full date on a labelled child,
    // while innerText contains only an ambiguous day number and price.
    if (!name && !typedInto) name = Array.from(el.querySelectorAll(":scope > [aria-label]"))
      .filter(child => child.getAttribute("aria-hidden") !== "true")
      .map(child => child.getAttribute("aria-label")).join(" ");
    if (!name && !typedInto && parseFloat(st.fontSize) > 0) name = (renderedText(el) || (BUTTON_TYPES.has(type) ? el.value : "") || "");
    if (!name && el.tagName === "SELECT") name = el.selectedOptions[0]?.label || "dropdown";
    if (!name && field && el.parentElement && el.parentElement.querySelectorAll('input,textarea,select').length === 1) {
      const labels = Array.from(el.parentElement.querySelectorAll('label')).filter(label => {
        const box = label.getBoundingClientRect();
        return box.width > 0 && box.height > 0 && getComputedStyle(label).visibility !== 'hidden';
      });
      name = labels.map(label => label.innerText).join(' ');
    }
    if (!name && field) {
      // Many forms use a nearby span/div or table heading instead of <label>.
      // Infer only one visible sibling label within a container with one field.
      let scope = el.parentElement;
      for (let depth=0; scope && depth<3 && !name; depth++, scope=scope.parentElement) {
        if (scope.querySelectorAll('input,textarea,select,[contenteditable]').length !== 1 || scope.querySelector('button,a,[role=button]')) break;
        const labels=Array.from(scope.children).filter(node => !node.contains(el) && !node.matches('input,textarea,select,[contenteditable]'))
          .filter(node => visibleRect(node) && getComputedStyle(node).visibility !== 'hidden' && parseFloat(getComputedStyle(node).fontSize)>0)
          .map(node => (node.innerText || '').replace(/\s+/g,' ').trim().replace(/:\s*$/,''))
          .filter(text => text.length>0 && text.length<=80);
        if (labels.length===1) name=labels[0];
      }
    }
    if (!name) name = el.getAttribute("title") || el.getAttribute("alt") || "";
    if (!name) name = el.getAttribute("name") || "";
    name = name.replace(/\s+/g, " ").trim();
    if (!name && (field || type === "checkbox" || type === "radio")) name = (type || el.tagName.toLowerCase()) + " input" + (el.id ? " (id=" + el.id + ")" : "");
    if (!name && imageControl) {
      // CSS image controls often have no accessible name. The public image
      // filename is useful labeling metadata, like an img alt or HTML id.
      const asset = st.content.match(/([^/]+)\.(?:png|svg|webp|gif|jpg)/i);
      if (asset) name = "icon " + asset[1].replace(/[-_]/g, " ");
    }
    if (!name && (pointer || previouslyInteractive)) name = "clickable " + el.tagName.toLowerCase();
    if (!name && shape) name = "shape " + el.tagName + " fill " + st.fill;
    if (!name && role === "slider") name = "slider handle";
    if (!name && scrollable) name = "scrollable " + el.tagName.toLowerCase();
    if (!name && visual) name = "visual " + el.tagName.toLowerCase() + " background " + st.backgroundColor +
      " size " + Math.round(r.width) + "x" + Math.round(r.height);
    if (!name) continue;
    if (/^\d{1,2}$/.test(name)) {
      const calendar=el.closest('.ui-datepicker');
      const heading=calendar?.querySelector('.ui-datepicker-title');
      if (heading && visibleRect(heading)) name=renderedText(heading)+' '+name;
    }
    name = name.slice(0, 120);
    const selected = el.getAttribute("aria-selected") || el.closest('[role="gridcell"]')?.getAttribute("aria-selected");
    if (selected === "true") name += " (selected)";
    const checked = (labelControl ? String(labelControl.checked) : el.getAttribute("aria-checked")) ??
      ((type === "radio" || type === "checkbox") ? String(el.checked) : null);
    if (checked !== null) name += checked === "true" ? " (checked)" : " (unchecked)";
    const key = [name.toLowerCase(), Math.round(r.left), Math.round(r.top), el.tagName].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    const visible=visibleRect(el);
    if (!visible) continue;
    const x = Math.round(visible.left + Math.min(visible.width, 1400) / 2);
    const y = Math.round(visible.top + visible.height / 2);
    const top = document.elementFromPoint(Math.max(0, Math.min(x, vw - 1)), Math.max(0, Math.min(y, vh - 1)));
    const covered = !!(top && !el.contains(top));
    el.setAttribute("data-tscu", String(sid));
    nodes.push(el);
    out.push({sid, tag: el.tagName.toLowerCase(), role: role || type,
              name, x, y, w: Math.round(r.width), h: Math.round(r.height),
              in_view: x > 0 && x < vw && y > 0 && y < vh, covered,
              href: el.tagName === "A" ? (el.href || "") : "",
              focused: document.activeElement === el, field, secret, draggable, readonly: !!el.readOnly, imageControl,
              scroll_y: scrollable ? Math.round(el.scrollTop) : 0,
              scroll_max: scrollable ? el.scrollHeight - el.clientHeight : 0,
              written_value: !secret && window.__tscuWrittenValues?.has(el) &&
                window.__tscuWrittenValues.get(el) === el.value ? el.value : null,
              options: el.tagName === "SELECT" ? Array.from(el.options).map((o,i) => ({index:i,label:o.label,disabled:o.disabled,selected:o.selected})) : []});
    sid++;
  }
  const nameCounts = new Map();
  out.forEach(o=>nameCounts.set(o.name,(nameCounts.get(o.name)||0)+1));
  for (const o of out) {
    if (o.field || (!o.imageControl && !["a","button"].includes(o.tag) && nameCounts.get(o.name)<2)) continue;
    let scope=nodes[o.sid].parentElement;
    for (let depth=0; scope && depth<3; depth++, scope=scope.parentElement) {
      const context=renderedText(scope);
      if (context && context!==o.name && context.length<=160) { o.context=context; break; }
    }
  }
  out.sort((a, b) => (Math.abs(a.y - b.y) > 8 ? a.y - b.y : a.x - b.x));
  out.forEach((o, i) => {
    // Keep the original node identity: querying by an ID already reassigned in
    // this permutation can select a different node (or produce duplicate IDs).
    nodes[o.sid].setAttribute("data-tscu", String(i));
    o.index = i;
  });
  // --- visible text: prices, dates, errors, everything that is not a control --------
  // Blocks in reading order, kept apart from `items` so a text block is never a click
  // target. Nothing inside a text control, a textbox role or an editable region is
  // read, so a field's contents and an unsent contenteditable draft stay on the page.
  const SKIP = "script,style,noscript,template,select,textarea,svg,[aria-hidden='true']," +
               "[contenteditable]:not([contenteditable='false'])," +
               "[role='textbox'],[role='searchbox'],[role='combobox']";
  const CONTROL = "a,button,input,select,textarea,summary,option,[onclick],[tabindex]";
  const INLINE = new Set(["B","STRONG","I","EM","U","S","SMALL","ABBR","CODE","MARK","SUB","SUP","SPAN"]);
  const TEXT_MAX = 120, TEXT_CHARS = 240;
  // Text nodes under their nearest block element, in DOM order. From the document
  // itself when there is no body yet (mid-load) or at all (an SVG or XML file).
  const groups = new Map();
  const walker = document.createTreeWalker(document.body || document, NodeFilter.SHOW_TEXT);
  for (let node; (node = walker.nextNode()); ) {
    if (!node.nodeValue.trim()) continue;
    let g = node.parentElement;
    while (g.parentElement && INLINE.has(g.tagName)) g = g.parentElement;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(node);
  }
  // Per text node, and only inside a block already found on screen, where it is cheap.
  // A shown block can still hold a skipped part, or an inline part with no box or
  // with visibility hidden.
  const range = document.createRange();
  const readable = (n, el) => {
    const p = n.parentElement;
    if (p.isContentEditable || p.closest(SKIP) || parseFloat(getComputedStyle(p).fontSize) === 0) return false;
    if (p === el) return true;
    range.selectNodeContents(n);
    return range.getClientRects().length > 0 && getComputedStyle(p).visibility !== "hidden";
  };
  const names = new Set(out.map(o => o.name.toLowerCase()));
  const textOut = [], textSeen = new Set();
  for (const [el, nodes] of groups) {
    if (el.matches(CONTROL) || ROLES.has((el.getAttribute("role") || "").toLowerCase())) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || !visibleRect(el)) continue;
    if (!(r.top < vh + 8 && r.bottom > -8 && r.left < vw + 8 && r.right > -8)) continue;  // before any style
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || st.display === "none" || parseFloat(st.opacity || "1") === 0) continue;
    // Read only as far as a block can use: a whole file in one <pre> stops early.
    let text = "";
    for (const n of nodes) {
      if (text.length > 2 * TEXT_CHARS) break;
      if (readable(n, el)) text += " " + n.nodeValue.replace(/\s+/g, " ");
    }
    text = text.replace(/\s+/g, " ").trim();
    const key = text.toLowerCase();
    // Too short, a copy of a control's label, or a repeat (nav bars, ARIA duplicates).
    if (text.length < 1 || names.has(key) || textSeen.has(key)) continue;
    textSeen.add(key);
    textOut.push({text: text.slice(0, TEXT_CHARS), x: Math.round(r.left), y: Math.round(r.top),
                  w: Math.round(r.width), h: Math.round(r.height)});
    if (textOut.length >= TEXT_MAX) break;
  }
  textOut.sort((a, b) => (Math.abs(a.y - b.y) > 8 ? a.y - b.y : a.x - b.x));
  const sc = document.scrollingElement || document.documentElement;
  const busy = Array.from(document.querySelectorAll('[aria-busy="true"],[role="progressbar"]')).some(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.top >= vh) return false;
    for (let node = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity) === 0) return false;
    }
    return true;
  });
  return {url: location.href, title: document.title, vw, vh, count: out.length, items: out,
          text: textOut, busy,
          scroll_y: Math.round(sc.scrollTop), scroll_max: Math.round(sc.scrollHeight - vh),
          candidates: total, below_fold: belowFold,
          can_scroll: sc.scrollHeight > vh + 4,
          history_len: history.length,
          fields: out.filter(o => o.field && !o.secret && !o.readonly && !o.covered).length};
})()
""".replace("__VISIBLE_RECT_HELPER__", VISIBLE_RECT_JS)


@dataclass(frozen=True)
class Element:
    index: int
    tag: str
    role: str
    name: str
    x: int
    y: int
    w: int
    h: int
    in_view: bool
    covered: bool
    href: str
    field: bool = False  # takes free text
    secret: bool = False  # asks for a password, a one-time code or card data: never typed into
    focused: bool = False
    options: list[dict] = dataclass_field(default_factory=list)
    scroll_y: int = 0
    scroll_max: int = 0
    written_value: str | None = None
    draggable: bool = False
    context: str = ""
    readonly: bool = False

    @property
    def typeable(self) -> bool:
        return self.field and not self.secret and not self.readonly

    def label(self) -> str:
        bits = [f"<{self.tag}>", repr(self.name)]
        if self.context:
            bits.append(f"within {self.context!r}")
        if self.readonly:
            bits.append("readonly: click to open its editor")
        if self.draggable:
            bits.append("draggable")
        bits.append(f"center=({self.x},{self.y})")
        if self.role:
            bits.append(f"role={self.role}")
        if self.focused:
            bits.append("focused")
        if self.href:
            bits.append(self.href[:70])
        if self.secret:
            bits.append("credential field")
        if not self.in_view:
            bits.append("off-screen")
        if self.covered:
            bits.append("covered by an overlay")
        return " ".join(bits)


@dataclass(frozen=True)
class TextBlock:
    """One visible text block: evidence for the classifier, never a click target."""

    text: str
    x: int
    y: int
    w: int
    h: int


@dataclass
class Page:
    url: str
    title: str
    vw: int
    vh: int
    items: list[Element]
    elapsed_ms: float
    raw_count: int
    can_scroll: bool = True
    history_len: int = 1
    field_count: int = 0
    scroll_y: int = 0
    scroll_max: int = 0
    candidates: int = 0
    below_fold: int = 0
    busy: bool = False
    text: list[TextBlock] = dataclass_field(default_factory=list)  # visible page text, evidence only

    @property
    def has_field(self) -> bool:
        return self.field_count > 0


def perceive(session: Any, *, budget: int = 120, text_budget: int = 120) -> Page:
    """One CDP round trip -> an ordered, labelled element list, plus the page's visible
    text as evidence blocks. No pixels."""
    start = time.perf_counter()
    data = session.evaluate(INTERACTIVE_JS) or {}
    elapsed = (time.perf_counter() - start) * 1000
    items = [
        Element(
            index=int(it.get("index", i)),
            tag=str(it.get("tag", "")),
            role=str(it.get("role", "")),
            name=str(it.get("name", "")),
            x=int(it.get("x", 0)),
            y=int(it.get("y", 0)),
            w=int(it.get("w", 0)),
            h=int(it.get("h", 0)),
            in_view=bool(it.get("in_view", True)),
            covered=bool(it.get("covered", False)),
            href=str(it.get("href", "")),
            field=bool(it.get("field", False)),
            secret=bool(it.get("secret", False)),
            focused=bool(it.get("focused", False)),
            options=list(it.get("options") or []),
            scroll_y=int(it.get("scroll_y", 0)),
            scroll_max=int(it.get("scroll_max", 0)),
            written_value=it.get("written_value"),
            draggable=bool(it.get("draggable", False)),
            context=str(it.get("context", "")),
            readonly=bool(it.get("readonly", False)),
        )
        # Covered background controls must not consume the budget before dialog
        # controls such as a calendar's Done button at the bottom of the screen.
        for i, it in enumerate(sorted(data.get("items") or [], key=lambda it: bool(it.get("covered")))[:budget])
    ]
    from dataclasses import replace

    checks = [e for e in items if e.role == "checkbox" and not e.covered]
    if len(checks) >= 6:
        xs = sorted(set(e.x for e in checks))
        ys = sorted(set(e.y for e in checks))
        if len(xs) >= 2 and len(ys) >= 2:
            items = [
                replace(e, name=e.name + f" [row {ys.index(e.y) + 1}, column {xs.index(e.x) + 1}]") if e in checks else e
                for e in items
            ]
    text = [
        TextBlock(
            text=str(tb.get("text", "")),
            x=int(tb.get("x", 0)),
            y=int(tb.get("y", 0)),
            w=int(tb.get("w", 0)),
            h=int(tb.get("h", 0)),
        )
        for tb in (data.get("text") or [])[:text_budget]
        if str(tb.get("text", "")).strip()
    ]
    return Page(
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        vw=int(data.get("vw", 0)),
        vh=int(data.get("vh", 0)),
        items=items,
        elapsed_ms=elapsed,
        raw_count=int(data.get("count", len(items))),
        can_scroll=bool(data.get("can_scroll", True)),
        history_len=int(data.get("history_len", 1)),
        field_count=int(data.get("fields", 0)),
        scroll_y=int(data.get("scroll_y", 0)),
        scroll_max=int(data.get("scroll_max", 0)),
        candidates=int(data.get("candidates", 0)),
        below_fold=int(data.get("below_fold", 0)),
        busy=bool(data.get("busy", False)),
        text=text,
    )


def to_json(page: Page) -> str:
    return json.dumps(
        {
            "url": page.url,
            "title": page.title,
            "elapsed_ms": round(page.elapsed_ms, 2),
            "items": [it.__dict__ for it in page.items],
            "text": [tb.__dict__ for tb in page.text],
        },
        indent=2,
    )
