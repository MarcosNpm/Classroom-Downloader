from classroom_dl import ui
from classroom_dl.api import Course


class FakeQuestion:
    def __init__(self, answers):
        self._answers = iter(answers)

    def ask(self):
        return next(self._answers)


def test_pick_courses_reprompts_when_nothing_is_selected(monkeypatch):
    calls = []
    answers = iter([[], ["curso-1"]])

    def fake_checkbox(*args, **kwargs):
        calls.append(kwargs)
        return FakeQuestion(answers)

    monkeypatch.setattr(ui.questionary, "checkbox", fake_checkbox)
    monkeypatch.setattr(ui, "_require_tty", lambda: None)

    result = ui.pick_courses([Course("curso-1", "Matemáticas para Informática")])

    assert result == ["curso-1"]
    assert len(calls) == 2
