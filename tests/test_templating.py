import pytest

from promptpivot import Message, PromptRenderError
from promptpivot.templating import build_renderer, checksum, detect_variables, guess_format


def test_python_basic_and_escapes():
    r = build_renderer("Hi {name}, {{name}} {n:03d}", "python")
    assert r({"name": "A", "n": 7}) == "Hi A, {name} 007"
    assert detect_variables("Hi {name}, {{name}} {n:03d}", "python") == ("name", "n")


@pytest.mark.parametrize(
    "tpl",
    [
        '{"character_location": "Paris"}',
        '{"a": {"b": [1, 2]}}',
        "{a.b} {a[0]} {a!r} {0} {} {a",
        "{{ jinja }} {% if x %}",
        "}} {{",
    ],
)
def test_python_leaves_other_braces_alone(tpl):
    assert build_renderer(tpl, "python")({}) == tpl
    assert detect_variables(tpl, "python") == ()


def test_python_json_with_variables():
    tpl = 'Reply as JSON like {"name": "{name}", "nested": {"n": {n:02d}}} for {name}.'
    assert (
        build_renderer(tpl, "python")({"name": "A", "n": 3})
        == 'Reply as JSON like {"name": "A", "nested": {"n": 03}} for A.'
    )
    with pytest.raises(PromptRenderError):
        build_renderer("{n:zz}", "python")({"n": 1})  # bad format spec


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


def test_guess_format():
    assert guess_format("Hi {name}") == "python"
    assert guess_format('{"a": 1}') == "python"
    assert guess_format("Hi {{ name }}") == "jinja"
    assert guess_format("{% if x %}y{% endif %}") == "jinja"
    assert guess_format([{"role": "user", "content": "{# c #}{{ q }}"}]) == "jinja"


def test_detect_variables_and_checksum():
    assert detect_variables("{b} {a} {b}", "python") == ("b", "a")
    assert detect_variables("{{ z }} {% for i in items %}{{ i }}{% endfor %}", "jinja") == ("items", "z")
    assert detect_variables([{"role": "u", "content": "{x}"}], "python") == ("x",)
    assert checksum("a", "python", {}) == checksum("a", "python", {}) != checksum("a", "jinja", {})
    with pytest.raises(PromptRenderError):
        build_renderer("x", "nope")
