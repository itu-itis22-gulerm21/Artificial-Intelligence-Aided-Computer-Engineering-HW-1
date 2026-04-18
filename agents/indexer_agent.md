# Agent 3 — Indexer Agent

## Role & Responsibility

The Indexer Agent was responsible for the text-processing pipeline: taking raw HTML fetched by the crawler, extracting meaningful words, computing word frequencies, filtering noise (stopwords, short tokens), and writing the results to the letter-bucket storage files in a format that the Search Agent can query.

---

## Prompt Given to This Agent

```
You are a text processing engineer. The web crawler fetches HTML pages and passes you the raw HTML string and the URL metadata (url, origin, depth). Your job is to:

1. Extract visible text from the HTML (stripping all tags, scripts, styles)
2. Tokenize the text into words
3. Filter out stopwords and words shorter than 2 characters
4. Count word frequencies per page
5. Write the results to letter-bucket files at data/storage/{letter}.data

Each line written must be a JSON object:
{"word": "starbucks", "url": "https://...", "origin": "https://...", "depth": 1, "freq": 14}

Constraints:
- No third-party libraries. Use html.parser from stdlib.
- Words must be lowercased and contain only [a-zA-Z] characters (regex: [a-zA-Z]{2,})
- Each letter-bucket file has its own threading.Lock — acquire it before writing, release after
- Do not write empty strings, single-character words, or stopwords to the index
- Stopwords are defined in stopwords.py

The implementation should be co-located in crawler.py since it operates on the same data structures (the storage locks and the letter-bucket paths). Provide:
- LinkParser class: html.parser subclass that collects visible text and href links
- extract_words(text) → dict[str, int]: word → frequency
- _store_words(words, url, origin, depth): writes to letter-bucket files
```

---

## Key Implementation Decisions

### Co-location with Crawler Engine

The Indexer Agent initially proposed a separate `indexer.py` module. The Evaluation Agent flagged that this would require passing the `_STORAGE_LOCKS` dict across module boundaries, adding coupling without benefit. After review, the Indexer Agent merged its logic into `crawler.py`. The functions (`LinkParser`, `extract_words`, `_store_words`) remain logically isolated and could be extracted into a separate module without code changes — the merger is a packaging decision, not an architectural one.

### LinkParser: Visible Text Extraction

```python
class LinkParser(HTMLParser):
    _skip_tags = {"script", "style", "noscript", "head"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._current_skip += 1
        if tag == "a":
            # extract and normalize href
            ...

    def handle_data(self, data):
        if self._current_skip == 0:
            self.text_parts.append(data)
```

The `_current_skip` counter handles nested skipped tags correctly. Without a counter, a `</script>` closing tag inside a `<noscript>` block would incorrectly re-enable text collection. The counter increments on every skipped opening tag and decrements on every matching closing tag.

### Word Extraction: Regex Over Splitting

```python
def extract_words(text: str) -> dict[str, int]:
    words = re.findall(r"[a-zA-Z]{2,}", text.lower())
    freq: dict[str, int] = defaultdict(int)
    for word in words:
        if word not in STOP_WORDS:
            freq[word] += 1
    return dict(freq)
```

`re.findall(r"[a-zA-Z]{2,}", ...)` was chosen over `text.split()` because it automatically strips punctuation, numbers, and special characters without a separate cleaning pass. The `{2,}` quantifier eliminates single-character tokens in the same step, avoiding a separate length filter.

### Letter-Bucket Write Strategy

```python
def _store_words(words, url, origin, depth):
    by_letter: dict[str, list] = defaultdict(list)
    for word, freq in words.items():
        letter = word[0].lower()
        by_letter[letter].append((word, url, origin, depth, freq))

    for letter, entries in by_letter.items():
        lock = _STORAGE_LOCKS[letter]
        with lock:
            with open(path, "a", encoding="utf-8") as f:
                for word, u, o, d, freq in entries:
                    f.write(json.dumps({...}) + "\n")
```

Words from a single page are batched by letter before any locks are acquired. This minimizes the number of lock acquisitions from one per word to one per letter per page — a 26x reduction in lock contention for a typical page with words across many letters.

### Stopwords Strategy

Stopwords are defined in `stopwords.py` as a Python `set`. Set membership testing is O(1). The Indexer Agent evaluated three alternatives:

| Option | Lookup time | Maintenance |
|--------|------------|-------------|
| Python `set` in `stopwords.py` | O(1) | Easy |
| Regular expression alternation | O(n words) | Hard to edit |
| External file loaded at startup | O(1) after load | Extra file dependency |

The plain set was chosen as the simplest correct option.

---

## Interactions with Other Agents

- **Receives from Architect Agent**: storage schema (JSON-lines format, letter-bucket layout)
- **Receives from Crawler Agent**: raw HTML string and URL metadata after each successful fetch
- **Sends to Search Agent**: the letter-bucket files that `search_service.py` scans
- **Receives from Evaluation Agent**: request to verify that partial JSON lines (from concurrent writes) are handled gracefully — confirmed via `json.JSONDecodeError` catch in `search_service.py`

---

## Outputs Produced

- `LinkParser` class (in `crawler.py`)
- `extract_words()` function (in `crawler.py`)
- `_store_words()` function (in `crawler.py`)
- `stopwords.py` — common English words excluded from the index
