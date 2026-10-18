import pytest

from promptdeck import Message, PromptRenderError
from promptdeck.templating import build_renderer, checksum, detect_variables


def test_python_basic_and_escapes():
    r = build_renderer("Hi {name}, {{literal}} {n:03d}", "python")
    assert r({"name": "A", "n": 7}) == "Hi A, {literal} 007"


@pytest.mark.parametrize("tpl", ["{a.b}", "{a[0]}", "{a!r}", "{0}", "{}", "{a:{b}}", "{a"])
def test_python_rejects_unsafe(tpl):
    with pytest.raises(PromptRenderError):
        build_renderer(tpl, "python")


def test_python_missing_variable_is_keyerror():
    with pytest.raises(KeyError):
        build_renderer("{a}", "python")({})


def test_jinja_sandbox_and_strict():
    r = build_renderer("Hi {{ name }}{% if vip %} (VIP){% endif %}", "jinja")
    assert r({"name": "A", "vip": True}) == "Hi A (VIP)"
    with pytest.raises(KeyError):
        r({"name": "A"})
    with pytest.raises(Exception):  # sandbox blocks attribute escapes
        build_renderer("{{ x.__class__.__mro__ }}", "jinja")({"x": 1})
    with pytest.raises(PromptRenderError):
        build_renderer("{% if %}", "jinja")


def test_chat_renders_each_message():
    r = build_renderer([{"role": "system", "content": "S {a}"}, {"role": "user", "content": "U {b}"}], "python")
    out = r({"a": 1, "b": 2})
    assert out == [Message(role="system", content="S 1"), Message(role="user", content="U 2")]


def test_detect_variables_and_checksum():
    assert detect_variables("{b} {a} {b}", "python") == ("b", "a")
    assert detect_variables("{{ z }} {% for i in items %}{{ i }}{% endfor %}", "jinja") == ("items", "z")
    assert detect_variables([{"role": "u", "content": "{x}"}], "python") == ("x",)
    assert checksum("a", "python", {}) == checksum("a", "python", {}) != checksum("a", "jinja", {})
    with pytest.raises(PromptRenderError):
        build_renderer("x", "nope")
