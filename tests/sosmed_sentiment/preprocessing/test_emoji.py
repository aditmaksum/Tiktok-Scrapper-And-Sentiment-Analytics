from sosmed_sentiment.preprocessing.emoji import extract_emoji


def test_emoji_is_removed_and_returned_separately():
    text, found = extract_emoji('bagus banget 😍👍')

    assert text.strip() == 'bagus banget'
    assert found == ['😍', '👍']


def test_text_without_emoji_is_unchanged():
    text, found = extract_emoji('halo dunia')

    assert text == 'halo dunia'
    assert found == []


def test_empty_string_does_not_raise():
    text, found = extract_emoji('')

    assert text == ''
    assert found == []


def test_none_does_not_raise():
    text, found = extract_emoji(None)

    assert text == ''
    assert found == []
