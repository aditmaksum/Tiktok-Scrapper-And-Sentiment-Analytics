from typing import Any, Dict, List

from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

# scikit-learn (Architecture.md §2) - TF-IDF unigram+bigram is a solved
# problem here, no reason to hand-roll it.
TOKEN_PATTERN: str = r'(?u)\b\w+\b'


def extract_top_keywords(
    documents: List[str],
    top_n: int = 20
) -> List[Dict[str, Any]]:
    """Top-N unigram+bigram keywords across documents, by summed TF-IDF score.

    documents: one string per comment, already preprocessed (stemmed tokens
    joined by whitespace) - see cli/analyze.py for where these strings come
    from. `count` is the raw term frequency across the corpus, computed
    separately from `score` (TF-IDF) because they answer different
    questions: score ranks importance, count answers "how often did people
    actually say this."

    Returns [] for no documents or a corpus with nothing left after
    preprocessing (e.g. every comment stripped to nothing) - scikit-learn
    raises on an empty vocabulary, which is not an error worth surfacing to
    the operator, just an empty result.
    """
    non_empty: List[str] = [doc for doc in documents if doc and doc.strip()]

    if not non_empty:
        return []

    tfidf = TfidfVectorizer(ngram_range=(1, 2), token_pattern=TOKEN_PATTERN)
    tfidf_matrix = tfidf.fit_transform(non_empty)

    if not tfidf.vocabulary_:
        return []

    counter = CountVectorizer(
        ngram_range=(1, 2), token_pattern=TOKEN_PATTERN, vocabulary=tfidf.vocabulary_
    )
    count_matrix = counter.fit_transform(non_empty)

    vocabulary: List[str] = list(tfidf.get_feature_names_out())
    scores = tfidf_matrix.sum(axis=0).A1
    counts = count_matrix.sum(axis=0).A1

    ranked = sorted(zip(vocabulary, scores, counts), key=lambda item: -item[1])

    return [
        {'keyword': keyword, 'score': round(float(score), 4), 'count': int(count)}
        for keyword, score, count in ranked[:top_n]
    ]


def extract_keywords_by_sentiment(
    documents_by_label: Dict[str, List[str]],
    top_n: int = 10
) -> Dict[str, List[Dict[str, Any]]]:
    """FR-05: top-N keywords per sentiment label, each label scored independently.

    Independent per-label corpora, not a slice of the overall ranking - a
    word can be a top negative-comment word without being a top word
    overall, and that distinction is the point of splitting by label.
    """
    return {
        label: extract_top_keywords(documents, top_n)
        for label, documents in documents_by_label.items()
    }
