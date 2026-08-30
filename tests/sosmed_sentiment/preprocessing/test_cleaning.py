from sosmed_sentiment.preprocessing.cleaning import clean


def test_url_is_removed():
    assert 'http' not in clean('bagus banget https://example.com cek deh')


def test_mention_is_removed():
    assert '@dokterrizkimrd' not in clean('@dokterrizkimrd bisa gak buat anak')


def test_whitespace_is_collapsed():
    assert clean('bagus    banget') == 'bagus banget'


def test_none_does_not_raise():
    assert clean(None) == ''
