"""Headless, local-only control integration check; no model calls."""

import tempfile
from pathlib import Path

from typesafe_computer_use._vendor.jev_ultrafast.browser import Browser
from typesafe_computer_use.browser import act
from typesafe_computer_use.browser.cdp import Chrome

with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "controls.html"
    fixture.write_text("""<!doctype html><html><body>
<style>input[type=radio]{display:none} .custom{cursor:pointer}</style>
<input id="nonstop" type="radio"><label for="nonstop">Direct service</label>
<input id="query" aria-label="Search" autofocus>
<span class="custom" onclick="document.body.dataset.clicked='yes'">Custom link</span>
<div role="tabpanel"><span class="custom">Panel link</span></div>
<div role="dialog" tabindex="0">Dialog container</div>
<section><div id="cards"><div><a href="#">First</a></div><div><a href="#">Second</a></div></div>
<ul><li class="active" id="page1"><a href="#">1</a></li><li id="page2"><a href="#">2</a></li></ul></section>
<form><textarea aria-label="Source">amber cedar</textarea><input aria-label="Answer"></form>
<p id="external">Invoice reference: AB123</p><div id="clock" role="timer">120 / 120sec</div>
<div id="scrollbox" aria-label="Notes" style="height:80px;width:200px;overflow:auto">
<div style="height:400px">Long notes</div></div>
</body></html>""")
    with Chrome() as chrome, chrome.attach() as session:
        act.navigate(session, fixture.as_uri())
        act.wait_for_load(session)
        browser = Browser(session)
        page = browser.observe(screenshot=False)
        assert any(a["label"] == "Panel link" for a in page["actions"])
        assert not any(a["label"] == "Dialog container" for a in page["actions"])
        session.evaluate("document.querySelector('#page1').className=''; document.querySelector('#page2').className='active'")
        page = browser.observe(screenshot=False)
        session.evaluate(
            "document.querySelector('#page1 a').setAttribute('aria-current','false'); document.querySelector('#page2 a').setAttribute('aria-current','page')"
        )
        page = browser.observe(screenshot=False)
        assert not next(a for a in page["actions"] if a["label"] == "1").get("current")
        second = next(a for a in page["actions"] if a["label"] == "Second")
        assert second["pagination"]["ordinal_if_uniform_pages"] == 4
        assert second["pagination"]["ordinal_from_observed_pages"] == 4
        label = next(a for a in page["actions"] if a["label"] == "Direct service")
        assert label["role"] == "radio" and label["checked"] == "false"
        assert not any(a["label"] == "Open Search" for a in page["actions"])
        browser.act(label, page)
        page = browser.observe(screenshot=False)
        assert next(a for a in page["actions"] if a["label"] == "Direct service")["checked"] == "true"
        custom = next(a for a in page["actions"] if a["label"] == "Custom link")
        browser.act(custom, page)
        assert session.evaluate("document.body.dataset.clicked") == "yes"
        page = browser.observe(screenshot=False)
        field = next(a for a in page["actions"] if a["label"] == "Answer" and a["kind"] == "fill")
        session.evaluate("document.querySelector('#clock').textContent='119 / 120sec'")
        assert browser.fresh(page, field), "Unrelated clock must not invalidate a field action"
        session.evaluate("document.querySelector('#external').textContent='Invoice reference: CD456'")
        assert not browser.fresh(page, field), "Changed external source text must invalidate generated text"
        page = browser.observe(screenshot=False)
        field = next(a for a in page["actions"] if a["label"] == "Answer" and a["kind"] == "fill")
        session.evaluate("document.querySelector('textarea').value='different source'")
        assert not browser.fresh(page, field), "Changed source values must invalidate generated text"
        page = browser.observe(screenshot=False)
        scroll = next(a for a in page["actions"] if a["kind"] == "scroll" and "Notes" in a["label"])
        browser.act(scroll, page)
        session.call("Runtime.evaluate", {"expression": "new Promise(r=>setTimeout(r,100))", "awaitPromise": True})
        assert session.evaluate("document.querySelector('#scrollbox').scrollTop") > 0
print("PASS: hidden radio labels, checked state, focused field, custom pointer control and real mouse input")
