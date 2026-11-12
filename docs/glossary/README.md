# Glossary format

These files are the second retrieval source for VibeMatch (the first is the song catalog).
Each `##` heading is one entry. Everything else is ignored by the loader.

```
## term
Related words: one, two, three
One or two plain sentences that start with the term.
```

- `Related words` are single words a listener might type instead of the term. A request word that
  matches an entry is also matched against the term and its related words.
- The sentences are facts the system may use when it explains a song of that genre, mood or tag.
  Keep them short, plain and true.
