import pytest

from sosmed_sentiment.errors import InvalidInputSchemaError
from sosmed_sentiment.ingest.tiktok_adapter import flatten_input


def video(aweme_id='1', comments=None, **extra):
    data = {'aweme_id': aweme_id, 'caption': 'a caption', 'comments': comments or []}
    data.update(extra)
    return data


def top_comment(comment_id='c1', username='user1', comment='halo', replies=None):
    data = {
        'comment_id': comment_id, 'username': username, 'comment': comment,
        'create_time': '2026-08-30T00:00:00'
    }
    if replies is not None:
        data['replies'] = replies
    return data


def test_a_valid_video_flattens_to_one_record_per_comment():
    flat = flatten_input([video(comments=[top_comment()])])

    assert len(flat) == 1
    assert flat[0]['comment_id'] == 'c1'
    assert flat[0]['video_id'] == '1'
    assert flat[0]['is_reply'] is False
    assert flat[0]['parent_comment_id'] is None


def test_a_reply_is_flattened_with_its_parent_id():
    reply = top_comment(comment_id='r1', username='replier')
    parent = top_comment(comment_id='c1', replies=[reply])

    flat = flatten_input([video(comments=[parent])])

    assert len(flat) == 2
    assert flat[1]['comment_id'] == 'r1'
    assert flat[1]['is_reply'] is True
    assert flat[1]['parent_comment_id'] == 'c1'


def test_video_author_username_is_denormalised_onto_every_comment():
    flat = flatten_input([video(
        comments=[top_comment()], video_author_username='dokterrizkimrd'
    )])

    assert flat[0]['video_author_username'] == 'dokterrizkimrd'


def test_missing_video_author_username_defaults_to_empty_string():
    flat = flatten_input([video(comments=[top_comment()])])

    assert flat[0]['video_author_username'] == ''


def test_root_must_be_an_array():
    with pytest.raises(InvalidInputSchemaError):
        flatten_input({'aweme_id': '1', 'comments': []})


def test_missing_aweme_id_raises():
    with pytest.raises(InvalidInputSchemaError) as error:
        flatten_input([{'comments': []}])

    assert 'aweme_id' in str(error.value)


def test_missing_comments_field_raises():
    with pytest.raises(InvalidInputSchemaError) as error:
        flatten_input([{'aweme_id': '1'}])

    assert 'comments' in str(error.value)


def test_an_empty_comments_array_is_valid_not_an_error():
    flat = flatten_input([video(comments=[])])

    assert flat == []


def test_a_comment_missing_a_required_field_names_the_comment_id():
    bad_comment = {'comment_id': 'c1', 'username': 'user1'}  # missing comment, create_time

    with pytest.raises(InvalidInputSchemaError) as error:
        flatten_input([video(comments=[bad_comment])])

    assert 'c1' in str(error.value)


def test_a_reply_nested_more_than_one_level_deep_raises():
    grandchild = top_comment(comment_id='g1')
    reply = top_comment(comment_id='r1', replies=[grandchild])
    parent = top_comment(comment_id='c1', replies=[reply])

    with pytest.raises(InvalidInputSchemaError) as error:
        flatten_input([video(comments=[parent])])

    assert 'nested' in str(error.value)
