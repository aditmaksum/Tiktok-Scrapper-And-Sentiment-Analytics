from sosmed_sentiment.filters.exclude_accounts import apply_exclusions, detect_top_accounts


def record(username, video_author_username=''):
    return {
        'username': username,
        'video_author_username': video_author_username,
        'excluded': False,
        'exclude_reason': None
    }


def test_manual_exclude_list_marks_internal_account():
    comments = [record('yaylesupport')]

    apply_exclusions(comments, ['yaylesupport'])

    assert comments[0]['excluded'] is True
    assert comments[0]['exclude_reason'] == 'internal_account'


def test_video_uploader_is_excluded_without_being_on_the_manual_list():
    comments = [record('dokterrizkimrd', video_author_username='dokterrizkimrd')]

    apply_exclusions(comments, [])

    assert comments[0]['excluded'] is True
    assert comments[0]['exclude_reason'] == 'video_uploader'


def test_matching_both_resolves_to_video_uploader_precedence():
    comments = [record('dokterrizkimrd', video_author_username='dokterrizkimrd')]

    apply_exclusions(comments, ['dokterrizkimrd'])

    assert comments[0]['exclude_reason'] == 'video_uploader'


def test_a_non_matching_comment_is_not_excluded():
    comments = [record('realcustomer', video_author_username='dokterrizkimrd')]

    apply_exclusions(comments, ['yaylesupport'])

    assert comments[0]['excluded'] is False
    assert comments[0]['exclude_reason'] is None


def test_matching_is_case_sensitive():
    comments = [record('DokterRizkiMRD', video_author_username='dokterrizkimrd')]

    apply_exclusions(comments, [])

    assert comments[0]['excluded'] is False


def test_empty_exclude_list_still_runs_without_error():
    comments = [record('realcustomer')]

    result = apply_exclusions(comments, [])

    assert result[0]['excluded'] is False


class TestDetectTopAccounts:

    def test_ranks_by_raw_frequency(self):
        comments = (
            [record('frequent')] * 3
            + [record('rare')] * 1
        )

        result = detect_top_accounts(comments)

        assert result[0]['username'] == 'frequent'
        assert result[0]['total_muncul'] == 3

    def test_an_excluded_account_names_its_reason(self):
        comments = [record('yaylesupport')]
        apply_exclusions(comments, ['yaylesupport'])

        result = detect_top_accounts(comments)

        assert result[0]['alasan'] == 'internal_account'

    def test_a_non_excluded_account_flags_for_manual_review(self):
        comments = [record('unknownacct')]

        result = detect_top_accounts(comments)

        assert result[0]['alasan'] == 'belum dikecualikan - cek manual'

    def test_respects_top_n(self):
        comments = [record('a'), record('b'), record('c')]

        assert len(detect_top_accounts(comments, top_n=2)) == 2
