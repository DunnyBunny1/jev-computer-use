"""Explicit headless-browser regression check; no models or external websites.

Run with `uv run python bench/check_dom_mapping.py`. Kept out of pytest because
the offline test suite deliberately cannot launch browsers.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from typesafe_computer_use.browser import act
from typesafe_computer_use.browser.cdp import Chrome
from typesafe_computer_use.browser.perceive import perceive

HTML = """<body style="height:2500px">
<a style="position:absolute;top:200px;left:50px" href="#first">DOM first</a>
<a style="position:absolute;top:50px;left:50px" href="#second">Visual first</a>
<a style="position:absolute;top:120px;left:50px" href="#third">Visual second</a>
<input style="position:absolute;top:250px;left:50px" type="password" value="never-log-me" aria-label="Password">
<a style="position:absolute;top:1200px;left:50px" href="#bottom">Below fold</a>
<div role="button" style="position:absolute;top:300px;left:50px"><span aria-label="Thursday, November 12, 2026">12</span></div>
<label style="position:absolute;top:350px;left:50px"><input style="opacity:0" id="direct" type="radio" name="stops">Nonstop only</label>
<label style="position:absolute;top:400px;left:50px">Draft<textarea>never-log-draft</textarea></label>
<div id="loading" role="progressbar" style="position:absolute;top:450px;left:50px;width:50px;height:4px">Loading</div>
<div style="position:absolute;top:480px;left:50px;width:40px;height:25px;font-size:0;cursor:pointer" id="card">concealed-card-value</div>
<div style="position:absolute;top:510px;left:50px"><label>Reference value</label><input id="unassociated"></div>
<div style="position:absolute;top:550px;left:50px">7</div>
<span style="position:absolute;top:580px;left:50px;cursor:pointer;content:url(send.svg)"></span>
<div style="position:absolute;left:400px;top:50px;width:100px;height:60px;overflow:auto;overflow-x:hidden">
<button style="display:block;height:40px;width:90px" onclick="window.chosen='one'">Clip one</button>
<button style="display:block;height:40px;width:90px" onclick="window.chosen='two'">Clip two</button>
<button style="display:block;height:40px;width:90px" onclick="window.chosen='three'">Clip three</button>
</div>
<div style="position:absolute;left:400px;top:480px"><input id="standalone"><button>Send form</button></div>
<input aria-label="City suggestions" class="ui-autocomplete-input" style="position:absolute;left:400px;top:400px">
<input aria-label="Date picker" readonly style="position:absolute;left:400px;top:440px">
<p style="position:absolute;left:400px;top:200px"><span>Project:</span><input></p>
<table style="position:absolute;left:400px;top:260px"><tr><th>Budget</th><td><input></td></tr></table>
<div style="position:absolute;left:400px;top:320px"><div>Owner</div><div><input></div></div>
"""


def main():
    with TemporaryDirectory() as tmp, Chrome() as chrome, chrome.attach() as session:
        fixture = Path(tmp) / "mapping.html"
        fixture.write_text(HTML)
        (Path(tmp) / "send.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><path d="M0 0L16 8L0 16Z"/></svg>'
        )
        act.navigate(session, fixture.as_uri())
        act.wait_for_load(session)
        for _ in range(2):
            page = perceive(session)
            assert page.busy
            assert "concealed-card-value" not in repr(page)
            assert any(e.name == "Reference value" for e in page.items)
            assert any(t.text == "7" for t in page.text)
            assert any(e.name == "icon send" for e in page.items)
            assert any(e.name == "text input (id=standalone)" for e in page.items)
            assert next(e for e in page.items if e.name == "City suggestions").role == "combobox"
            assert not next(e for e in page.items if e.name == "Date picker").typeable
            assert all(any(e.name == label for e in page.items) for label in ["Project", "Budget", "Owner"])
            assert not any(e.name == "Clip three" for e in page.items)
            clipped = next(e for e in page.items if e.name == "Clip two")
            assert clipped.y == 100
            act.click(session, clipped.index, clipped, page)
            assert session.evaluate("window.chosen") == "two"
            actual = session.evaluate(
                'Array.from(document.querySelectorAll("[data-tscu]")).map(e => '
                '({index:Number(e.dataset.tscu),href:e.href || ""}))'
            )
            assert len({row["index"] for row in actual}) == len(actual)
            for element in page.items:
                matched = [row for row in actual if row["index"] == element.index]
                assert len(matched) == 1 and matched[0]["href"] == element.href, (element, matched)
            assert "never-log-me" not in repr(page.items) + repr(page.text)
            assert "never-log-draft" not in repr(page.items) + repr(page.text)
            assert not any(e.name == "Below fold" for e in page.items)
            assert any(e.name == "Thursday, November 12, 2026" for e in page.items)
            assert any(e.name == "Nonstop only (unchecked)" for e in page.items)
        session.evaluate(
            'document.getElementById("card").style.fontSize="20px";document.getElementById("card").style.cursor="auto"'
        )
        assert any(e.name == "concealed-card-value" for e in perceive(session).items)
        radio = next(e for e in page.items if e.name == "Nonstop only (unchecked)")
        act.click(session, radio.index, radio, page)
        page = perceive(session)
        assert any(e.name == "Nonstop only (checked)" for e in page.items)
        session.evaluate('document.getElementById("loading").style.opacity="0"')
        page = perceive(session)
        assert not page.busy
        draft = next(e for e in page.items if e.tag == "textarea")
        assert draft.written_value is None
        act.type_text(session, draft.index, "agent-owned text")
        assert next(e for e in perceive(session).items if e.tag == "textarea").written_value == "agent-owned text"
        session.evaluate("document.querySelector('textarea').value='new private user draft'")
        page = perceive(session)
        assert next(e for e in page.items if e.tag == "textarea").written_value is None
        assert "new private user draft" not in repr(page)
        target = next(e for e in page.items if e.name == "DOM first")
        act.click(session, target.index, target, page)
        assert session.evaluate("location.hash") == "#first"
        session.evaluate("""document.body.innerHTML='<style>button{cursor:pointer;width:70px;height:35px}</style>'+
          Array.from({length:90},(_,i)=>'<div role="gridcell" tabindex="-1" style="display:inline-block;cursor:pointer"><button><span aria-label="Choice '+i+'">'+i+'</span></button></div>').join('')+
          '<button id="finish" onclick="window.finished=true"><span>Done</span></button>'""")
        page = perceive(session)
        assert len(page.items) == 91
        finish = next(e for e in page.items if e.name == "Done")
        act.click(session, finish.index, finish, page)
        assert session.evaluate("window.finished")
        print("PASS: control mapping, clipping, fields and dense nested controls; secrets and offscreen content excluded")


if __name__ == "__main__":
    main()
