from sosmed_sentiment.sentiment.lexicon_classifier import (
    classify, get_lexicon, load_lexicon, score_tokens
)


def test_a_clear_positive_score_is_labelled_positif():
    lexicon = get_lexicon(None)
    result = classify(['bagus', 'mantap'], lexicon)

    assert result['sentiment_label'] == 'positif'
    assert result['sentiment_method'] == 'lexicon'


def test_a_clear_negative_score_is_labelled_negatif():
    lexicon = get_lexicon(None)
    result = classify(['jelek', 'kecewa'], lexicon)

    assert result['sentiment_label'] == 'negatif'


def test_no_matched_tokens_is_labelled_netral():
    lexicon = get_lexicon(None)
    result = classify(['entahlah', 'randomword'], lexicon)

    assert result['sentiment_label'] == 'netral'
    assert result['oov_ratio'] == 1.0


def test_empty_token_list_is_netral_with_zero_oov():
    lexicon = get_lexicon(None)
    result = classify([], lexicon)

    assert result['sentiment_label'] == 'netral'
    assert result['oov_ratio'] == 0.0


def test_load_lexicon_reads_a_csv_file(tmp_path):
    path = tmp_path / 'lexicon.csv'
    path.write_text('bagus,0.8\njelek,-0.8\n', encoding='utf-8')

    lexicon = load_lexicon(str(path))

    assert lexicon == {'bagus': 0.8, 'jelek': -0.8}


def test_load_lexicon_skips_an_unreadable_score(tmp_path):
    path = tmp_path / 'lexicon.csv'
    path.write_text('bagus,0.8\njelek,not-a-number\n', encoding='utf-8')

    lexicon = load_lexicon(str(path))

    assert lexicon == {'bagus': 0.8}


def test_score_tokens_averages_matched_words():
    score, oov = score_tokens(['bagus', 'unknown'], {'bagus': 0.8})

    assert score == 0.8
    assert oov == 0.5
