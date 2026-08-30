from sosmed_sentiment.preprocessing.stemming import stem


def test_words_are_reduced_to_their_root_form():
    assert stem(['bermain-main', 'senangnya']) == ['main', 'senang']


def test_empty_list_returns_empty_list():
    assert stem([]) == []
