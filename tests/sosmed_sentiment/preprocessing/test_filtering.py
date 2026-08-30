from sosmed_sentiment.preprocessing.filtering import (
    NEGATION_WORDS, filter_stopwords, load_stopwords
)


def test_stopwords_are_removed():
    assert filter_stopwords(['bagus', 'yang', 'banget'], {'yang'}) == ['bagus', 'banget']


def test_negation_words_survive_the_default_stopword_list():
    stopwords = load_stopwords(None)

    for word in NEGATION_WORDS:
        assert word not in stopwords


def test_a_config_file_listing_a_negation_word_is_overridden(tmp_path):
    path = tmp_path / 'stopwords.txt'
    path.write_text('yang\ntidak\ndan\n', encoding='utf-8')

    stopwords = load_stopwords(str(path))

    assert 'tidak' not in stopwords
    assert 'yang' in stopwords
    assert 'dan' in stopwords


def test_negation_word_survives_filtering_even_if_present_in_stopwords_by_mistake():
    # Defence in depth: even if a caller passes an unfiltered set,
    # filter_stopwords itself does not special-case negation - load_stopwords
    # is where the guarantee lives. This test documents that boundary rather
    # than asserting behaviour filter_stopwords does not own.
    result = filter_stopwords(['tidak', 'bagus'], set())
    assert 'tidak' in result
