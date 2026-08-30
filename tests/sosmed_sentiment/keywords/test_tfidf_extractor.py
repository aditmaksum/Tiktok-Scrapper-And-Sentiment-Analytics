from sosmed_sentiment.keywords.tfidf_extractor import (
    extract_keywords_by_sentiment, extract_top_keywords
)


def test_top_keywords_are_ranked_by_score():
    docs = ['bagus mantap', 'bagus mantap', 'jelek']

    result = extract_top_keywords(docs, top_n=5)

    keywords = [item['keyword'] for item in result]
    assert 'bagus' in keywords
    assert 'jelek' in keywords


def test_count_reflects_raw_frequency_not_tfidf_score():
    docs = ['bagus', 'bagus', 'bagus', 'jelek']

    result = extract_top_keywords(docs, top_n=5)

    by_keyword = {item['keyword']: item for item in result}
    assert by_keyword['bagus']['count'] == 3
    assert by_keyword['jelek']['count'] == 1


def test_bigrams_are_included():
    docs = ['tidak bagus', 'tidak bagus', 'sangat bagus']

    result = extract_top_keywords(docs, top_n=20)

    keywords = [item['keyword'] for item in result]
    assert 'tidak bagus' in keywords


def test_empty_document_list_returns_empty():
    assert extract_top_keywords([]) == []


def test_all_blank_documents_return_empty_not_a_crash():
    assert extract_top_keywords(['', '  ', '']) == []


def test_extract_by_sentiment_scores_each_label_independently():
    result = extract_keywords_by_sentiment({
        'positif': ['bagus mantap', 'bagus'],
        'negatif': ['jelek parah']
    }, top_n=5)

    assert 'bagus' in [item['keyword'] for item in result['positif']]
    assert 'jelek' in [item['keyword'] for item in result['negatif']]
