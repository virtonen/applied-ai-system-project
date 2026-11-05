from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parent.parent / "app.py")


def run_app(**widgets):
    """Start the app, set widgets by key (selectbox/slider/radio/checkbox), and run it."""
    at = AppTest.from_file(APP, default_timeout=30).run()
    for key, value in widgets.items():
        for kind in (at.selectbox, at.slider, at.select_slider, at.radio, at.checkbox, at.multiselect):
            try:
                kind(key=key).set_value(value)
                break
            except KeyError:
                continue
        else:
            raise KeyError(key)
    return at.run()


def songs(at):
    return list(at.dataframe[0].value["Song"])


def page_text(at):
    return "\n".join(m.value for m in at.markdown)


LOFI = dict(genre="lofi", mood="chill", energy=0.4, valence=0.6, acousticness=0.8)
POP = dict(genre="pop", mood="happy", energy=0.9, valence=0.85, acousticness=0.1)
EXTREME = dict(genre="metal", mood="peaceful", energy=0.0, valence=1.0, acousticness=0.0)


def test_page_loads_with_no_errors():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value.endswith("VibeMatch")
    assert len(at.dataframe[0].value) == 5


def test_lofi_listener_gets_lofi_songs_first_and_no_warning():
    at = run_app(**LOFI)
    assert not at.exception
    assert songs(at)[:2] == ["Library Rain", "Midnight Coding"]
    assert len(at.warning) == 0


def test_how_many_slider_changes_the_number_of_rows():
    at = run_app(**LOFI, k=8)
    assert len(at.dataframe[0].value) == 8


def test_scoring_mode_changes_the_results():
    balanced = songs(run_app(**POP, mode="balanced"))
    mood_first = songs(run_app(**POP, mode="mood-first"))
    assert balanced != mood_first
    assert balanced.index("Gym Hero") < mood_first.index("Gym Hero") or "Gym Hero" not in mood_first


def test_diversity_checkbox_adds_penalty_reasons():
    assert "diversity penalty" not in page_text(run_app(**LOFI))
    assert "diversity penalty" in page_text(run_app(**LOFI, diverse=True))


def test_weak_match_shows_a_warning():
    at = run_app(**EXTREME)
    assert not at.exception
    assert len(at.warning) == 1
    assert "No strong match" in at.warning[0].value


def test_advanced_preferences_appear_in_the_reasons():
    at = run_app(**LOFI, use_popularity=True, use_decade=True, use_instrumentalness=True, avoid_explicit=True,
                 mood_tags=["study", "cozy"])
    text = page_text(at)
    for expected in ("popularity close to target", "release decade", "instrumentalness close to target",
                     "clean lyrics", "mood tags match"):
        assert expected in text, expected


def test_every_mode_and_diversity_setting_renders_without_errors():
    for mode in ("balanced", "genre-first", "mood-first", "energy-focused"):
        for diverse in (False, True):
            at = run_app(**POP, mode=mode, diverse=diverse)
            assert not at.exception, (mode, diverse)
            assert len(at.dataframe[0].value) == 5
