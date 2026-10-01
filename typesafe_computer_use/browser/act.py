"""Execute a decision through CDP. Each handler returns a history line.

Every action is a real input event (`Input.dispatchMouseEvent` /
`Input.insertText`), not a JS `.click()`, so frameworks that listen for genuine
pointer events behave exactly as they would for a human.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .cdp import CDPError, Session
from .perceive import VISIBLE_RECT_JS, Element, Page, perceive

# CDP expects these key codes; enter is the only one the loop needs beyond typing.
KEYS = {
    "enter": ("Enter", "\r"),
    "escape": ("Escape", "\u001b"),
    "tab": ("Tab", "\t"),
}


def _select(index: int) -> str:
    return f'[data-tscu="{index}"]'


def element_rect(session: Session, index: int) -> dict | None:
    return session.evaluate(
        f"""(() => {{
          {VISIBLE_RECT_JS}
          const el = document.querySelector({_select(index)!r});
          if (!el) return null;
          const r = visibleRect(el);
          if (!r) return null;
          return {{x: Math.round(r.left + Math.min(r.width,1400)/2), y: Math.round(r.top + r.height/2),
                   w: Math.round(r.width), h: Math.round(r.height), vw: innerWidth, vh: innerHeight,
                   hit: el.contains(document.elementFromPoint(Math.round((r.left+r.right)/2), Math.round((r.top+r.bottom)/2)))}};
        }})()"""
    )


def is_gone(session: Session, index: int) -> bool:
    return session.evaluate(f"!document.querySelector({_select(index)!r})") is True


def click(session: Session, index: int, element: Element, page: Page) -> str:
    """Real mouse press/release at the element's centre."""
    if not element.in_view:
        session.evaluate(
            f"""(() => {{
              const el = document.querySelector({_select(index)!r});
              if (el) el.scrollIntoView({{block: "center", inline: "center"}});
              return true;
            }})()"""
        )
        time.sleep(0.05)
    rect = element_rect(session, index)
    if rect is None:
        return f"click {index} FAILED (element gone)"
    if not rect.get("hit", True):
        return f"click {index} refused: covered target"
    x, y = int(rect["x"]), int(rect["y"])
    session.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
    # Hover can swap an icon asset or move a control. Recheck the actual hit
    # target after hover rather than pressing where the old control used to be.
    for _attempt in range(6):
        hovered = element_rect(session, index)
        if hovered and hovered.get("hit", True):
            nx, ny = int(hovered["x"]), int(hovered["y"])
            if (nx, ny) == (x, y):
                break
            x, y = nx, ny
            session.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
        time.sleep(0.05)
    else:
        return f"click {index} refused: target did not settle after hover"
    for kind in ("mousePressed", "mouseReleased"):
        session.call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1 if kind == "mousePressed" else 0},
        )
    return f"click [{index}] {element.name[:60]!r} at ({x},{y})" + (
        f" within {element.context[:100]!r}" if element.context else ""
    )


def focus(session: Session, index: int) -> bool:
    return (
        session.evaluate(
            f"""(() => {{
          const el = document.querySelector({_select(index)!r});
          if (!el) return false;
          el.focus();
          if (el.select) {{ try {{ el.select(); }} catch (e) {{}} }}
          return document.activeElement === el;
        }})()"""
        )
        is True
    )


def type_text(session: Session, index: int, text: str) -> str:
    if not focus(session, index):
        return f"type FAILED (could not focus [{index}])"
    session.call("Input.insertText", {"text": text})
    session.evaluate(f"""(() => {{
      const el = document.querySelector({json.dumps(_select(index))});
      if (el && String(el.type).toLowerCase() !== 'password' && el.value === {json.dumps(text)}) {{
        window.__tscuWrittenValues ??= new WeakMap();
        window.__tscuWrittenValues.set(el, {json.dumps(text)});
      }}
      return true;
    }})()""")
    return f"type {text!r} into [{index}]"


def select_option(session: Session, element: Element, option_index: int) -> str:
    # Native select is not an OS popup in DOM snapshots. Selecting an enumerated
    # option and firing its normal events matches WebDriver/Playwright semantics.
    if not any(o["index"] == option_index and not o.get("disabled") for o in element.options):
        return "select refused: option missing or disabled"
    changed = session.evaluate(f"""(() => {{
      const el = document.querySelector({json.dumps(_select(element.index))});
      if (!el || el.tagName !== 'SELECT' || el.disabled || !el.options[{option_index}] || el.options[{option_index}].disabled) return false;
      el.focus(); el.selectedIndex={option_index};
      el.dispatchEvent(new Event('input', {{bubbles:true}}));
      el.dispatchEvent(new Event('change', {{bubbles:true}})); return true;
    }})()""")
    return f"select [{element.index}] option {option_index}: {'ok' if changed else 'refused'}"


def field_value(session: Session, index: int) -> str | None:
    """What a field holds after the loop typed into it, for the verify check. A password field
    is never read: the loop never types into one, and this makes sure of it a second time."""
    value = session.evaluate(
        f"""(() => {{ const el = document.querySelector({_select(index)!r});
                     if (!el || el.value === undefined || String(el.type).toLowerCase() === "password") return null;
                     return String(el.value); }})()"""
    )
    return None if value is None else str(value)


def clear_field(session: Session, index: int) -> None:
    focus(session, index)
    session.call(
        "Input.dispatchKeyEvent",
        {"type": "keyDown", "modifiers": 4, "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65},
    )
    session.call(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", "modifiers": 4, "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65},
    )
    session.call("Input.insertText", {"text": ""})
    session.call(
        "Input.dispatchKeyEvent", {"type": "keyDown", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8}
    )
    session.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8})


def press(session: Session, key: str) -> str:
    k, text = KEYS[key]
    for event in ("keyDown", "keyUp"):
        session.call(
            "Input.dispatchKeyEvent",
            {
                "type": event,
                "key": k,
                "text": text if event == "keyDown" else "",
                "unmodifiedText": text,
                "windowsVirtualKeyCode": {"enter": 13, "escape": 27, "tab": 9}[key],
            },
        )
    return f"press {key}"


def scroll(session: Session, lines: int, page: Page, target: Element | None = None) -> str:
    # Keep overlap in small menus/feeds instead of skipping entire unseen rows.
    distance = min(abs(lines) * 120, max(20, round((target.h if target else page.vh) * 0.65)))
    delta = distance if lines > 0 else -distance
    session.call(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseWheel",
            "x": max(1, target.x if target else page.vw // 2),
            "y": max(1, target.y if target else page.vh // 2),
            "deltaX": 0,
            "deltaY": delta,
        },
    )
    return f"scroll {'down' if lines > 0 else 'up'} {distance}px" + (f" inside {target.name}" if target else "")


def navigate(session: Session, url: str, *, timeout_ms: int = 15000) -> str:
    session.call("Page.navigate", {"url": url})
    return f"navigate {url}"


def wait_for_load(session: Session, *, timeout_ms: int = 15000, settle_ms: int = 120) -> float:
    """Fixed-sleep variant, kept for callers that want deterministic pacing."""
    start = time.perf_counter()
    deadline = start + timeout_ms / 1000
    while time.perf_counter() < deadline:
        if session.evaluate("document.readyState") == "complete":
            break
        time.sleep(0.03)
    time.sleep(settle_ms / 1000)
    return (time.perf_counter() - start) * 1000


def fingerprint(page: Page) -> tuple:
    """Cheap identity for 'is this still the same page?'. The text is part of it: a form
    error or a loaded price can be the only thing that changed."""
    return (
        page.url,
        page.title,
        page.scroll_y,
        page.busy,
        tuple(
            (
                e.index,
                e.name,
                e.x,
                e.y,
                e.focused,
                e.covered,
                e.scroll_y,
                e.written_value,
                tuple(o.get("selected") for o in e.options),
            )
            for e in page.items
        ),
        tuple(tb.text for tb in page.text),
    )


def observe_until_changed(
    session: Session,
    before: tuple | None,
    *,
    timeout_ms: int = 300,
    poll_ms: int = 8,
    budget: int = 120,
    settle_ms: int = 0,
) -> tuple[Page, float, bool]:
    """Perceive until the page differs from `before`. Returns the post-action page.

    This replaces the settle sleep entirely. The observation we need for the
    *next* decision doubles as the wait for *this* action, so waiting costs no
    extra round trips: in the common case the change lands within ~20-40ms and
    we detect it on the first or second poll.

    The timeout is deliberately short. A page that has not changed in 300ms is
    better handled by the loop's own `wait` action than by stalling here.
    """
    start = time.perf_counter()
    if before is None:
        page = perceive(session, budget=budget)
        return page, (time.perf_counter() - start) * 1000, True
    deadline = start + timeout_ms / 1000
    last_fp, stable_since, page = None, start, None
    while True:
        try:
            page = perceive(session, budget=budget)
        except CDPError as exc:
            # A navigation briefly destroys the document's JavaScript context.
            if time.perf_counter() >= deadline or not any(
                term in str(exc) for term in ("context", "Cannot read properties of null")
            ):
                raise
            time.sleep(poll_ms / 1000)
            continue
        now = time.perf_counter()
        fp = fingerprint(page)
        if fp != last_fp:
            stable_since, last_fp = now, fp
        if fp != before and (not settle_ms or ((page.items or page.text) and now - stable_since >= settle_ms / 1000)):
            return page, (now - start) * 1000, True
        if now >= deadline:
            break
        time.sleep(poll_ms / 1000)
    return page, (time.perf_counter() - start) * 1000, fingerprint(page) != before


def go_back(session: Session) -> str:
    session.evaluate("history.back(); true")
    return "back"


def snapshot(session: Session, **kwargs: Any) -> Page:
    return perceive(session, **kwargs)


def drag(session: Session, source: Element, target: Element) -> str:
    """Pointer gesture, with release guaranteed even on a failed move."""
    if source.index == target.index or not source.draggable or source.covered or target.covered:
        return "drag refused: invalid or covered endpoints"
    a, b = element_rect(session, source.index), element_rect(session, target.index)
    if not a or not b:
        return "drag refused: endpoint disappeared"
    x, y = a["x"], a["y"]
    tx, ty = b["x"], b["y"]
    # Cross the destination's centre so sortable lists register the new slot.
    if abs(ty - y) >= abs(tx - x):
        ty += 3 if ty > y else -3
    else:
        tx += 3 if tx > x else -3
    if not (0 < x < a["vw"] and 0 < y < a["vh"] and 0 < tx < b["vw"] and 0 < ty < b["vh"]):
        return "drag refused: endpoint outside viewport"
    session.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    session.call(
        "Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1}
    )
    try:
        for n in range(1, 13):
            x, y = a["x"] + (tx - a["x"]) * n / 12, a["y"] + (ty - a["y"]) * n / 12
            session.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left", "buttons": 1})
            time.sleep(0.016)
    finally:
        session.call(
            "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1}
        )
    return f"drag {source.name!r} onto position of {target.name!r}"


def adjust_slider(session: Session, element: Element, amount: int) -> str:
    if element.role not in {"slider", "range"} or element.covered or not -100 <= amount <= 100 or amount == 0:
        return "slider adjustment refused"
    if not focus(session, element.index):
        return "slider focus failed"
    key, code = ("ArrowRight", 39) if amount > 0 else ("ArrowLeft", 37)
    for _ in range(abs(amount)):
        for event in ("keyDown", "keyUp"):
            session.call("Input.dispatchKeyEvent", {"type": event, "key": key, "code": key, "windowsVirtualKeyCode": code})
    return f"adjust slider {element.name!r} by {amount} keyboard steps"
