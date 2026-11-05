"""Streamlit UI for the Music Recommender. Run with: python -m streamlit run app.py"""

from pathlib import Path

import streamlit as st

from src.recommender import DEFAULT_MODE, SCORING_MODES, load_songs
from src.retrieval import SongIndex, search_and_rank

DATA_PATH = Path(__file__).parent / "data" / "songs.csv"
WEAK_MATCH_SCORE = 0.6  # below this, the best result is called a weak match


@st.cache_data
def get_songs():
    return load_songs(str(DATA_PATH))


@st.cache_resource
def get_index():
    return SongIndex(get_songs())


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
    st.caption("A small content-based music recommender. Every score comes with its reasons.")

    songs = get_songs()
    query, prefs, mode, diverse, k = build_prefs(songs)
    results = search_and_rank(get_index(), query, prefs, k=k, mode=mode, diverse=diverse)

    if not results:
        st.warning(
            f"Nothing fits: no songs match \"{query}\". "
            "Try different or fewer words, or clear the search box."
        )
        return

    if results[0][1] < WEAK_MATCH_SCORE:
        st.warning(
            f"No strong match: the best score is only {results[0][1]:.2f}. "
            "These songs are the closest the catalog has, not a good fit."
        )

    heading = f"Top {len(results)} songs ({mode}{', mixed up' if diverse else ''})"
    st.subheader(heading + (f" for \"{query}\"" if query.strip() else ""))
    st.dataframe(
        [
            {
                "#": rank,
                "Song": song["title"],
                "Artist": song["artist"],
                "Genre": song["genre"],
                "Mood": song["mood"],
                "Score": round(score, 2),
            }
            for rank, (song, score, _) in enumerate(results, start=1)
        ],
        hide_index=True,
        width="stretch",
    )

    st.subheader("Why these songs?")
    for rank, (song, score, explanation) in enumerate(results, start=1):
        with st.expander(f"#{rank}  {song['title']} by {song['artist']}  (score {score:.2f})", expanded=rank == 1):
            for reason in explanation.split("; "):
                st.write(f"- {reason}")


main()
