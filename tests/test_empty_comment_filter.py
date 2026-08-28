from tiktokcomment.tiktokcomment import TiktokComment


def raw(cid, text, reply_total=0):
    """A raw comment dict shaped like the fields the parser reads."""
    return {
        'cid': cid,
        'text': text,
        'create_time': 1735689600,
        'digg_count': 0,
        'reply_comment_total': reply_total,
        'user': {
            'unique_id': 'u%s' % cid,
            'nickname': 'n%s' % cid,
            'avatar_thumb': {'url_list': ['http://example.test/a.jpg']}
        },
        'share_info': {'title': 'a caption', 'url': 'http://example.test/v'}
    }


class FakeApi:
    """Serves canned pages so nothing here touches the network."""

    def __init__(self, pages, reply_pages=None):
        self.pages = pages
        self.reply_pages = reply_pages or {}
        self.cursors = []

    def __call__(self, path, params):
        if path == 'comment/list/':
            cursor = params['cursor']
            self.cursors.append(cursor)
            index = cursor // 50
            if index >= len(self.pages):
                return {'comments': [], 'has_more': 0}
            page = self.pages[index]
            return {
                'comments': page,
                'has_more': 1 if index + 1 < len(self.pages) else 0
            }

        replies = self.reply_pages.get(params['comment_id'], [])
        return {'comments': replies, 'has_more': 0}


def scraper_with(api, **kwargs):
    scraper = TiktokComment(request_delay=(0.0, 0.0), **kwargs)
    # __get is name-mangled; patching it keeps the rest of the class real.
    setattr(scraper, '_TiktokComment__get', api)
    return scraper


# A comment can come back with an empty text and nothing else: no image_list,
# status 1, not hidden. Probed against the live API on 2026-08-28, they are
# genuinely blank rather than sticker or photo comments, so they carry nothing
# to read or score, and must not spend a slot of the per-video cap.
def test_blank_comments_are_dropped():
    api = FakeApi([[raw('1', 'real one'), raw('2', ''), raw('3', 'real two')]])

    result = scraper_with(api).get_all_comments('v')

    assert [c.comment for c in result.comments] == ['real one', 'real two']


def test_blank_comments_do_not_spend_the_cap():
    """Three usable comments must survive a cap of 3 despite two blanks."""
    api = FakeApi([[
        raw('1', 'a'), raw('2', ''), raw('3', 'b'), raw('4', '   '), raw('5', 'c')
    ]])

    result = scraper_with(api, max_comments=3).get_all_comments('v')

    assert [c.comment for c in result.comments] == ['a', 'b', 'c']
    assert result.total_collected == 3


def test_whitespace_only_counts_as_blank():
    api = FakeApi([[raw('1', '   \n\t '), raw('2', 'real')]])

    result = scraper_with(api).get_all_comments('v')

    assert [c.comment for c in result.comments] == ['real']


def test_emoji_only_comments_are_kept():
    """An emoji is text: it carries sentiment and must not be filtered."""
    api = FakeApi([[raw('1', '\U0001f60d'), raw('2', '')]])

    result = scraper_with(api).get_all_comments('v')

    assert [c.comment for c in result.comments] == ['\U0001f60d']


def test_keep_empty_restores_the_old_behaviour():
    api = FakeApi([[raw('1', 'real'), raw('2', '')]])

    result = scraper_with(api, keep_empty=True).get_all_comments('v')

    assert [c.comment for c in result.comments] == ['real', '']


def test_blank_replies_do_not_spend_the_reply_cap():
    api = FakeApi(
        pages=[[raw('1', 'parent', reply_total=4)]],
        reply_pages={'1': [
            raw('r1', ''), raw('r2', 'reply one'),
            raw('r3', ''), raw('r4', 'reply two')
        ]}
    )

    result = scraper_with(api, max_replies=2).get_all_comments('v')

    replies = result.comments[0].replies
    assert [r.comment for r in replies] == ['reply one', 'reply two']


# The cursor advances by what the API returned, not by what survived the
# filter. Advancing by the filtered count would re-request the same page.
def test_cursor_advances_by_the_unfiltered_page_size():
    page_one = [raw(str(n), '' if n % 2 else 'text %d' % n) for n in range(50)]
    page_two = [raw('x%d' % n, 'more %d' % n) for n in range(10)]
    api = FakeApi([page_one, page_two])

    scraper_with(api, max_comments=100).get_all_comments('v')

    # 50 came back and 25 survived. The second request must start at 50, not
    # at 25, or half the first page would arrive twice.
    assert api.cursors == [0, 50]


def test_a_page_of_only_blanks_still_advances_the_cursor():
    """Otherwise the same page comes back forever."""
    api = FakeApi([
        [raw(str(n), '') for n in range(50)],
        [raw('x', 'finally something')]
    ])

    result = scraper_with(api).get_all_comments('v')

    assert [c.comment for c in result.comments] == ['finally something']
    assert api.cursors[:2] == [0, 50]


def test_the_skipped_count_is_recorded():
    api = FakeApi([[raw('1', ''), raw('2', 'real'), raw('3', '')]])
    scraper = scraper_with(api)

    scraper.get_all_comments('v')

    assert scraper.skipped_empty == 2


def test_caption_is_read_even_from_a_blank_comment():
    """share_info rides on the raw page, so filtering must not lose it."""
    blank = raw('1', '')
    api = FakeApi([[blank, raw('2', 'real')]])

    result = scraper_with(api).get_all_comments('v')

    assert result.caption == 'a caption'
