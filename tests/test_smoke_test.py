import pytest

from tiktokcomment import runner
from tiktokcomment.errors import SchemaError, BlockedError
from tiktokcomment.typing import Comments


def page(comment_count):
    """A Comments page carrying a given number of placeholder comments."""
    return Comments(
        caption='',
        video_url='',
        comments=[object()] * comment_count,
        has_more=0,
        aweme_id='x'
    )


class FakeScraper:
    """Stands in for TiktokComment, recording which videos were probed."""

    def __init__(self, results):
        self.results = results
        self.asked = []

    def __call__(self, *args, **kwargs):
        return self

    def get_comments(self, aweme_id, size=None, with_replies=None):
        self.asked.append(aweme_id)
        outcome = self.results[aweme_id]
        if isinstance(outcome, Exception):
            raise outcome
        return page(outcome)


@pytest.fixture
def fake(monkeypatch):
    def install(results):
        scraper = FakeScraper(results)
        monkeypatch.setattr(runner, 'TiktokComment', scraper)
        return scraper
    return install


# Regression: ISSUE-005 - the smoke test probed only the first video in the
# CSV, so a batch was blocked whenever that video happened to have its
# comments turned off. In the first real dataset 2 of 11 videos came back
# empty with a perfectly valid response, and one of them was first in the file.
# Found by /qa on 2026-08-28
# Report: .gstack/qa-reports/qa-report-tiktok-comment-scrapper-2026-08-28.md
def test_first_video_empty_does_not_block_the_batch(fake):
    scraper = fake({'a': 0, 'b': 5, 'c': 5})

    runner.smoke_test(['a', 'b', 'c'])

    assert scraper.asked == ['a', 'b']


def test_several_empty_videos_in_a_row_do_not_block_the_batch(fake):
    scraper = fake({'a': 0, 'b': 0, 'c': 0, 'd': 7})

    runner.smoke_test(['a', 'b', 'c', 'd'])

    assert scraper.asked == ['a', 'b', 'c', 'd']


def test_probing_stops_at_the_first_video_with_comments(fake):
    scraper = fake({'a': 3, 'b': 3})

    runner.smoke_test(['a', 'b'])

    assert scraper.asked == ['a']


def test_every_probe_empty_is_a_failure(fake):
    fake({'a': 0, 'b': 0, 'c': 0})

    with pytest.raises(SchemaError) as raised:
        runner.smoke_test(['a', 'b', 'c'])

    message = str(raised.value)
    assert 'no comments on any of 3 video(s)' in message
    # Naming them lets the operator check those videos by hand.
    assert 'a, b, c' in message


def test_probing_is_capped(fake):
    """A long CSV of empty videos must not become a long probe run."""
    ids = [str(n) for n in range(50)]
    scraper = fake({video: 0 for video in ids})

    with pytest.raises(SchemaError):
        runner.smoke_test(ids)

    assert len(scraper.asked) == runner.SMOKE_TEST_VIDEOS


def test_a_block_is_raised_immediately(fake):
    """A refused request is the endpoint failing, not a quiet video."""
    scraper = fake({'a': BlockedError('captcha page'), 'b': 5})

    with pytest.raises(BlockedError):
        runner.smoke_test(['a', 'b'])

    assert scraper.asked == ['a']
