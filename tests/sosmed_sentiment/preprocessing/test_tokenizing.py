from sosmed_sentiment.preprocessing.tokenizing import tokenize


def test_text_splits_into_word_tokens():
    assert tokenize('tidak bagus sekali') == ['tidak', 'bagus', 'sekali']


def test_punctuation_is_not_a_token():
    assert tokenize('bagus, banget!') == ['bagus', 'banget']


def test_empty_string_returns_empty_list():
    assert tokenize('') == []


def test_none_does_not_raise():
    assert tokenize(None) == []
