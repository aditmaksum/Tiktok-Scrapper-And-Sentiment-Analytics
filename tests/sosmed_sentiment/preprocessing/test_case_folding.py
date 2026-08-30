from sosmed_sentiment.preprocessing.case_folding import case_fold


def test_uppercase_becomes_lowercase():
    assert case_fold('BAGUS Banget') == 'bagus banget'


def test_none_does_not_raise():
    assert case_fold(None) == ''
