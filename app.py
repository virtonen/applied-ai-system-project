"""Streamlit UI for the Music Recommender. Run with: python -m streamlit run app.py"""

import logging
import os
from pathlib import Path

import streamlit as st

from src.guardrails import DataError
from src.logging_utils import log_event
from src.pipeline import search
from src.recommender import DEFAULT_MODE, SCORING_MODES, load_songs
from src.retrieval import SongIndex

# The song file can be changed with the VIBEMATCH_DATA environment variable
DATA_PATH = os.environ.get("VIBEMATCH_DATA") or str(Path(__file__).parent / "data" / "songs.csv")


@st.cache_data
def get_songs(path):
    return load_songs(path)


@st.cache_resource
def get_index(path):
    return SongIndex(get_songs(path))


def build_prefs(songs):
    """Draw the sidebar and return (search text, preferences dict, mode, diverse, k)."""
    st.sidebar.header("Search")
    query = st.sidebar.text_input(
        "Describe what you want (optional)", key="search",
        placeholder="e.g. cozy rainy study", help="Only songs that match these words are ranked.",
    )

    st.sidebar.header("Your taste")
    genres = sorted({s["genre"] for s in songs})
    moods = sorted({s["mood"] for s in songs})
    tags = sorted({t for s in songs for t in s["mood_tags"]})

    prefs = {
        "genre": st.sidebar.selectbox("Favorite genre", genres, key="genre"),
        "mood": st.sidebar.selectbox("Favorite mood", moods, key="mood"),
        "energy": st.sidebar.slider("Energy", 0.0, 1.0, 0.7, 0.05, key="energy"),
        "valence": st.sidebar.slider("Valence (how happy it sounds)", 0.0, 1.0, 0.6, 0.05, key="valence"),
        "acousticness": st.sidebar.slider("Acousticness", 0.0, 1.0, 0.3, 0.05, key="acousticness"),
    }

    with st.sidebar.expander("Advanced preferences"):
        if st.checkbox("Care about popularity", key="use_popularity"):
            prefs["popularity"] = st.slider("Popularity", 0, 100, 60, key="popularity")
        if st.checkbox("Care about release decade", key="use_decade"):
            prefs["decade"] = st.select_slider("Decade", [1960, 1970, 1980, 1990, 2000, 2010, 2020], 2010, key="decade")
        chosen_tags = st.multiselect("Mood tags", tags, key="mood_tags")
        if chosen_tags:
            prefs["mood_tags"] = chosen_tags
        if st.checkbox("Care about instrumentalness", key="use_instrumentalness"):
            prefs["instrumentalness"] = st.slider("Instrumentalness", 0.0, 1.0, 0.5, 0.05, key="instrumentalness")
        if st.checkbox("Avoid explicit songs", key="avoid_explicit"):
            prefs["avoid_explicit"] = True

    st.sidebar.header("How to rank")
    mode = st.sidebar.radio("Scoring mode", list(SCORING_MODES), index=list(SCORING_MODES).index(DEFAULT_MODE), key="mode")
    diverse = st.sidebar.checkbox("Mix up artists and genres (diversity penalty)", key="diverse")
    k = st.sidebar.slider("How many songs", 3, 10, 5, key="k")
    return query, prefs, mode, diverse, k


def main():
    st.set_page_config(page_title="VibeMatch", page_icon="🎧", layout="wide")
    st.title("🎧 VibeMatch")
    st.caption("A small content-based music recommender. Every score comes with its reasons and a confidence level.")

    try:
        songs = get_songs(DATA_PATH)
    except DataError as error:
        log_event("load_songs", level=logging.ERROR, path=DATA_PATH, error=str(error))
        st.error(f"The song list could not be loaded. {error}")
        return

    query, prefs, mode, diverse, k = build_prefs(songs)
    outcome = search(get_index(DATA_PATH), query, prefs, k=k, mode=mode, diverse=diverse)

    if outcome.status == "invalid_input":
        st.error(f"Please check your input. {outcome.message}")
        return
    if outcome.status == "error":
        st.error(outcome.message)
        return
    if outcome.status == "nothing_fits":
        st.warning(f"{outcome.message} Try different or fewer words, or clear the search box.")
        return

    top = outcome.top_confidence
    if top.label == "Low":
        st.warning(
            f"Low confidence ({top.value:.2f}): the best score is only {outcome.results[0].score:.2f}. "
            "These songs are the closest the catalog has, not a good fit."
        )
    else:
        st.caption(f"Overall confidence: {top.label} ({top.value:.2f})")

    heading = f"Top {len(outcome.results)} songs ({mode}{', mixed up' if diverse else ''})"
    st.subheader(heading + (f' for "{outcome.query}"' if outcome.query else ""))
    st.dataframe(
        [
            {
                "#": rank,
                "Song": r.song["title"],
                "Artist": r.song["artist"],
                "Genre": r.song["genre"],
                "Mood": r.song["mood"],
                "Score": round(r.score, 2),
                "Confidence": f"{r.confidence.label} ({r.confidence.value:.2f})",
            }
            for rank, r in enumerate(outcome.results, start=1)
        ],
        hide_index=True,
        width="stretch",
    )

    st.subheader("Why these songs?")
    for rank, r in enumerate(outcome.results, start=1):
        title = f"#{rank}  {r.song['title']} by {r.song['artist']}  (score {r.score:.2f}, {r.confidence.label} confidence)"
        with st.expander(title, expanded=rank == 1):
            for reason in r.explanation.split("; "):
                st.write(f"- {reason}")
            st.write(f"- confidence {r.confidence.value:.2f}: {r.confidence.breakdown()}")


main()
