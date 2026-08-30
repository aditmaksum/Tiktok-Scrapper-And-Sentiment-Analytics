from sosmed_sentiment.preprocessing.normalizing import normalize


def test_negation_slang_is_mapped_to_the_standard_negation_word():
    assert normalize('gak bagus') == 'tidak bagus'


def test_elongated_characters_are_collapsed():
    assert normalize('baguuuus') == 'baguus'


def test_a_word_with_no_mapping_is_unchanged():
    assert normalize('mantap') == 'mantap'


def test_none_does_not_raise():
    assert normalize(None) == ''
