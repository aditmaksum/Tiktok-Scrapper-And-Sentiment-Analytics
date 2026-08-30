import json

from click.testing import CliRunner

from sosmed_sentiment.cli.analyze import main


def write_input(tmp_path, videos):
    path = tmp_path / 'comments.json'
    path.write_text(json.dumps(videos), encoding='utf-8')
    return str(path)


def video(aweme_id='1', comments=None, video_author_username=''):
    return {
        'aweme_id': aweme_id, 'caption': 'caption', 'comments': comments or [],
        'video_author_username': video_author_username
    }


def top_comment(comment_id, username, text):
    return {
        'comment_id': comment_id, 'username': username, 'comment': text,
        'create_time': '2026-08-30T00:00:00'
    }


def test_a_valid_run_writes_analysis_result_and_exits_zero(tmp_path):
    input_path = write_input(tmp_path, [
        video(comments=[
            top_comment('c1', 'user1', 'bagus banget produknya'),
            top_comment('c2', 'user2', 'jelek parah gak recommended')
        ])
    ])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)

    assert data['meta']['total_comments_analyzed'] == 2
    assert data['sentiment_summary']['positif'] >= 1
    assert data['sentiment_summary']['negatif'] >= 1
    for comment in data['comments']:
        assert comment['sentiment_method'] == 'lexicon'


def test_an_invalid_schema_exits_2_and_writes_nothing(tmp_path):
    input_path = write_input(tmp_path, [{'aweme_id': '1'}])  # missing comments
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 2
    import os
    assert not os.path.exists(output_path)


def test_video_uploader_comment_is_excluded_from_the_result(tmp_path):
    input_path = write_input(tmp_path, [
        video(
            comments=[
                top_comment('c1', 'realcustomer', 'bagus banget'),
                top_comment('c2', 'dokterrizkimrd', 'terima kasih ya')
            ],
            video_author_username='dokterrizkimrd'
        )
    ])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)

    assert data['meta']['total_comments_analyzed'] == 1
    assert data['meta']['total_comments_excluded_internal'] == 1
    assert data['comments'][0]['username'] == 'realcustomer'


def test_missing_input_file_fails_before_writing_anything(tmp_path):
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(
        main, ['--input', str(tmp_path / 'does-not-exist.json'), '--output', output_path]
    )

    assert result.exit_code != 0
    import os
    assert not os.path.exists(output_path)
