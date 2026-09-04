import json
import os

from unittest.mock import MagicMock, patch

import pytest

from loguru import logger

from sosmed_sentiment.errors import LLMCallError, NarrativeGuardrailError
from sosmed_sentiment.report import llm_insights


# --- fixtures --------------------------------------------------------------

def fake_response(content):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _metrics(classified_total=100):
    return {
        'net_overall': 12.0,
        'classified_total': classified_total,
        'total_comments': classified_total + 5,
        'sentiment_counts': {
            'positif': 60, 'negatif': 30, 'netral': 10, 'tidak_terklasifikasi': 5
        },
        'sentiment_pct': {
            'positif_pct': 60.0, 'negatif_pct': 30.0, 'netral_pct': 10.0, 'unclassified_pct': 4.5
        },
        'data_quality': {
            'unclassified_count': 5, 'unclassified_pct': 4.5,
            'llm_escalation_pct': 10.0, 'llm_failure_pct': 0.0, 'method_breakdown': {}
        },
        'trend': [],
        'trend_last_delta': None,
        'engagement': {
            'total_likes': 0, 'net_by_likes': 0.0, 'net_by_likes_trimmed': 0.0,
            'top10_like_share_pct': 0.0
        },
        'top_comments': {'positif': [], 'negatif': []},
        'keywords_distinctive': {'positif': [], 'negatif': [], 'netral': []},
        'video_leaderboard': {
            'best': [], 'worst': [], 'loudest': [],
            'median_net': 0.0, 'eligible_count': 0, 'total_count': 0
        },
        'explorer_rows': [],
        'sample_video_count': 1
    }


def _tier_rows(kol_net=23.0, affiliate_net=26.8, official_net=23.0):
    return [
        {
            'tier': 'kol', 'label': 'KOL', 'net': kol_net, 'video_count': 61,
            'total_count': 3621, 'pct_of_total': 50.0,
            'top_themes': [{'theme': 'usia kelayakan', 'count': 40}],
            'keywords_distinctive': [{'keyword': 'aman'}]
        },
        {
            'tier': 'affiliate', 'label': 'Affiliate', 'net': affiliate_net, 'video_count': 460,
            'total_count': 2798, 'pct_of_total': 30.0,
            'top_themes': [{'theme': 'harga beli', 'count': 20}],
            'keywords_distinctive': [{'keyword': 'murah'}]
        },
        {
            'tier': 'official', 'label': 'Official', 'net': official_net, 'video_count': 54,
            'total_count': 2056, 'pct_of_total': 20.0,
            'top_themes': [], 'keywords_distinctive': []
        }
    ]


def _valid_llm_json():
    return {
        'headline': [{'title': 'Sentimen bersih +12.0', 'body': 'Net sentimen keseluruhan +12.0.'}],
        'risk': [{'title': 'Risiko', 'body': 'Sebagian besar komentar bersifat netral.'}],
        'actions': [{'title': 'Aksi', 'body': 'Audit video dengan net sentimen terendah.'}]
    }


def _capture_logs():
    messages = []
    sink_id = logger.add(messages.append, format='{message}')
    return messages, sink_id


# === T1/T13/T14/T20 - citation guardrail unit tests ========================

def test_json_shape_headline_as_dict_is_rejected_as_guardrail_error():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    bad = {'headline': {'not': 'a list'}, 'risk': [], 'actions': []}
    with pytest.raises(NarrativeGuardrailError):
        llm_insights._validate_shape(bad)


def test_json_shape_item_missing_body_is_rejected():
    bad = {
        'headline': [{'title': 'x'}],
        'risk': [{'title': 'y', 'body': 'z'}],
        'actions': [{'title': 'a', 'body': 'b'}]
    }
    with pytest.raises(NarrativeGuardrailError):
        llm_insights._validate_shape(bad)


def test_json_shape_body_as_int_is_rejected():
    bad = {
        'headline': [{'title': 'x', 'body': 123}],
        'risk': [{'title': 'y', 'body': 'z'}],
        'actions': [{'title': 'a', 'body': 'b'}]
    }
    with pytest.raises(NarrativeGuardrailError):
        llm_insights._validate_shape(bad)


def test_json_shape_valid_input_passes_through_unchanged():
    valid = _valid_llm_json()
    result = llm_insights._validate_shape(valid)
    assert result == valid


def test_exact_matching_number_passes_guardrail():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    body = 'Net sentimen keseluruhan berada di +12.0.'
    assert llm_insights._validate_claim(body, payload, set()) is None


def test_rounding_tolerance_within_bounds_passes():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    # KOL net is 23.0 - 23.05 is within the 0.15 tolerance.
    body = 'Net sentimen KOL sekitar +23.05.'
    assert llm_insights._validate_claim(body, payload, set()) is None


def test_number_not_present_anywhere_is_rejected():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    body = 'Net sentimen keseluruhan mencapai +987.6.'
    reason = llm_insights._validate_claim(body, payload, set())
    assert reason is not None
    assert '987.6' in reason


def test_body_with_zero_numbers_and_no_causal_connector_passes():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    body = 'Sebagian besar komentar bersifat netral dan mengikuti pola musiman.'
    assert llm_insights._validate_claim(body, payload, set()) is None


def test_numeric_membership_but_wrong_entity_is_rejected_f1():
    """F1: a number that IS somewhere in the payload (affiliate's 26.8) but
    attributed to a different tier (KOL) in the claim must be rejected -
    flat membership alone would incorrectly pass this."""
    payload = llm_insights.build_payload(_metrics(), _tier_rows(kol_net=23.0, affiliate_net=26.8))
    body = 'Net sentimen KOL: +26.8, jauh di atas tipe akun lain.'
    reason = llm_insights._validate_claim(body, payload, set())
    assert reason is not None
    assert 'Affiliate' in reason or 'KOL' in reason


def test_numeric_collision_across_entities_resolves_by_nearest_label_t14():
    """Decision #20/T14: KOL and Official share the identical net (23.0,
    a tie). A claim attributing that shared number to Affiliate (whose real
    net is different, 26.8) must still be rejected - proving the binding
    resolves by the claim's actual nearest-preceding label, not by
    first-match against the flat value set."""
    payload = llm_insights.build_payload(
        _metrics(), _tier_rows(kol_net=23.0, official_net=23.0, affiliate_net=26.8)
    )
    bad_body = 'Net sentimen Affiliate: +23.0, mirip tipe akun lain.'
    assert llm_insights._validate_claim(bad_body, payload, set()) is not None

    # The correct attribution (KOL, which genuinely is 23.0) still passes
    # despite the tie with Official.
    good_body = 'Net sentimen KOL: +23.0, konsisten dengan tipe akun lain.'
    assert llm_insights._validate_claim(good_body, payload, set()) is None


def test_causal_connector_supported_by_theme_data_passes():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    known_terms = llm_insights._known_causal_terms(payload)
    assert 'usia kelayakan' in known_terms
    body = 'Komentar KOL banyak menyinggung usia kelayakan karena target pembeli adalah orang tua.'
    assert llm_insights._validate_claim(body, payload, known_terms) is None


def test_causal_connector_unsupported_by_theme_data_is_rejected():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    known_terms = llm_insights._known_causal_terms(payload)
    body = 'Net sentimen affiliate lebih tinggi karena kontennya lebih otentik.'
    reason = llm_insights._validate_claim(body, payload, known_terms)
    assert reason is not None
    assert 'karena' in reason


def test_run_citation_guardrail_rejects_whole_response_on_one_bad_claim():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    narrative = {
        'headline': [{'title': 'ok', 'body': 'Net sentimen keseluruhan +12.0.'}],
        'risk': [{'title': 'bad', 'body': 'Net sentimen KOL: +999.9.'}],
        'actions': [{'title': 'ok', 'body': 'Aksi lanjut.'}]
    }
    with pytest.raises(NarrativeGuardrailError):
        llm_insights.run_citation_guardrail(narrative, payload)


def test_min_narrative_volume_constant_is_30_t20():
    assert llm_insights.MIN_NARRATIVE_VOLUME == 30


# === T4 - cache key stability / miss / accepted-only ========================

def test_cache_key_is_stable_across_identical_payloads():
    payload_a = llm_insights.build_payload(_metrics(), _tier_rows())
    payload_b = llm_insights.build_payload(_metrics(), _tier_rows())
    assert llm_insights.cache_key(payload_a) == llm_insights.cache_key(payload_b)


def test_cache_key_changes_on_any_metrics_change():
    key_before = llm_insights.cache_key(llm_insights.build_payload(_metrics(), _tier_rows()))
    key_after = llm_insights.cache_key(
        llm_insights.build_payload(_metrics(), _tier_rows(kol_net=99.0))
    )
    assert key_before != key_after


def test_cache_write_then_read_round_trips(tmp_path):
    cache_path = str(tmp_path / 'narrative.json')
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    key = llm_insights.cache_key(payload)
    narrative = _valid_llm_json()

    llm_insights._write_cache(cache_path, key, narrative)
    result = llm_insights._read_cache(cache_path, key)

    assert result == narrative


def test_cache_read_with_mismatched_key_is_a_miss(tmp_path):
    cache_path = str(tmp_path / 'narrative.json')
    llm_insights._write_cache(cache_path, 'some-old-key', _valid_llm_json())

    assert llm_insights._read_cache(cache_path, 'a-different-key') is None


def test_corrupt_cache_file_is_treated_as_miss_and_logged_warning(tmp_path):
    cache_path = str(tmp_path / 'narrative.json')
    with open(cache_path, 'w', encoding='utf-8') as handle:
        handle.write('{not valid json')

    messages, sink_id = _capture_logs()
    try:
        result = llm_insights._read_cache(cache_path, 'any-key')
    finally:
        logger.remove(sink_id)

    assert result is None
    assert any('rusak' in m or 'tidak terbaca' in m for m in messages)


def test_atomic_write_leaves_no_tmp_file_behind(tmp_path):
    path = str(tmp_path / 'narrative.json')
    llm_insights._atomic_write_json(path, {'a': 1})

    assert os.path.exists(path)
    assert not os.path.exists(path + '.tmp')


# === T2/T5/T6/T18 - retry-then-fallback state machine, transport retry,
# volume floor, explicit timeout ============================================

@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_first_attempt_success_returns_llm_accepted_no_retry(mock_openai_cls):
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(json.dumps(_valid_llm_json()))
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_LLM_ACCEPTED
    assert result['source'] == 'llm'
    assert client.chat.completions.create.call_count == 1


@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_reject_then_retry_then_accept_is_llm_accepted(mock_openai_cls, mock_sleep):
    bad_shape = json.dumps({'headline': {}, 'risk': [], 'actions': []})
    good = json.dumps(_valid_llm_json())
    client = MagicMock()
    client.chat.completions.create.side_effect = [fake_response(bad_shape), fake_response(good)]
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_LLM_ACCEPTED
    assert client.chat.completions.create.call_count == 2


@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_reject_twice_falls_back_to_deterministic_narrative(mock_openai_cls, mock_sleep):
    bad_shape = json.dumps({'headline': {}, 'risk': [], 'actions': []})
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(bad_shape)
    mock_openai_cls.return_value = client

    metrics = _metrics()
    result = llm_insights.generate_narrative_with_guardrail(
        metrics, _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_RETRIED_THEN_FALLBACK
    assert result['source'] == 'fallback'
    # fallback is the SAME deterministic narrative insights.build_narrative() produces
    from sosmed_sentiment.report import insights as insights_mod
    assert result['narrative'] == insights_mod.build_narrative(metrics)


@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_transport_failure_falls_back_never_raises(mock_openai_cls, mock_sleep):
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception('connection refused')
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_RETRIED_THEN_FALLBACK
    assert result['source'] == 'fallback'


@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_empty_choices_falls_back_with_clear_message_not_typeerror(mock_openai_cls, mock_sleep):
    """A router that cuts a reasoning model off mid-answer can return a
    response with an empty `choices` list. This must be rescued the same as
    any other transport failure, with a readable log message - not surface
    as a raw "'NoneType' object is not subscriptable" from indexing an empty
    list (observed against a real local nemotron-3-ultra-free endpoint)."""
    response = MagicMock()
    response.choices = []
    client = MagicMock()
    client.chat.completions.create.return_value = response
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_RETRIED_THEN_FALLBACK
    assert result['source'] == 'fallback'
    assert "'NoneType'" not in (result.get('reject_reason') or '')
    assert 'tidak berisi choices' in (result.get('reject_reason') or '')


@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_empty_content_falls_back_with_clear_message(mock_openai_cls, mock_sleep):
    """Same failure family as the empty-choices case above, but the model
    returned a choice with a null/blank message.content (e.g. it was still
    "thinking" - reasoning field populated - when the response got cut)."""
    mock_openai_cls.return_value = MagicMock(
        chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=fake_response(''))))
    )

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_RETRIED_THEN_FALLBACK
    assert result['source'] == 'fallback'
    assert 'respons LLM kosong' in (result.get('reject_reason') or '')


def test_second_attempt_itself_raising_unexpected_exception_still_falls_back_f2():
    """T2/F2: an exception type NOT caught by the inner (LLMCallError,
    NarrativeGuardrailError) handler must still be rescued by the top-level
    except Exception - D4's 'narrative section is never empty' promise
    holds even for a bug in the retry/guardrail logic itself."""
    with patch(
        'sosmed_sentiment.report.llm_insights._generate_once',
        side_effect=[NarrativeGuardrailError('first reject'), RuntimeError('unexpected bug')]
    ):
        metrics = _metrics()
        result = llm_insights.generate_narrative_with_guardrail(
            metrics, _tier_rows(), model='gpt-test', api_key='key', base_url=''
        )

    assert result['status'] == llm_insights.BANNER_RETRIED_THEN_FALLBACK
    assert result['source'] == 'fallback'


@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_below_volume_floor_never_calls_the_llm_client_t5(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(classified_total=llm_insights.MIN_NARRATIVE_VOLUME),
        _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_BELOW_VOLUME_FLOOR
    client.chat.completions.create.assert_not_called()


@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_no_llm_configured_never_calls_the_client(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='', api_key='', base_url=''
    )

    assert result['status'] == llm_insights.BANNER_NO_LLM_CONFIGURED
    client.chat.completions.create.assert_not_called()


@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_no_narrative_flag_short_circuits_before_llm_config_check(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url='',
        no_narrative=True
    )

    assert result['status'] == llm_insights.BANNER_NARRATIVE_DISABLED
    client.chat.completions.create.assert_not_called()


@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_client_is_constructed_with_an_explicit_timeout_t18(mock_openai_cls):
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(json.dumps(_valid_llm_json()))
    mock_openai_cls.return_value = client

    llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
    )

    _, kwargs = mock_openai_cls.call_args
    assert kwargs.get('timeout') == llm_insights.REQUEST_TIMEOUT_SECONDS


# === T4 - cache integration: accepted narrative cached, fallback never cached

@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_accepted_narrative_is_cached_and_reused_without_a_second_call(mock_openai_cls, tmp_path):
    cache_path = str(tmp_path / 'narrative.json')
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(json.dumps(_valid_llm_json()))
    mock_openai_cls.return_value = client

    metrics, tiers = _metrics(), _tier_rows()
    first = llm_insights.generate_narrative_with_guardrail(
        metrics, tiers, model='gpt-test', api_key='key', base_url='', cache_path=cache_path
    )
    assert first['status'] == llm_insights.BANNER_LLM_ACCEPTED
    assert client.chat.completions.create.call_count == 1

    second = llm_insights.generate_narrative_with_guardrail(
        metrics, tiers, model='gpt-test', api_key='key', base_url='', cache_path=cache_path
    )
    assert second['status'] == llm_insights.BANNER_LLM_ACCEPTED
    assert second['narrative'] == first['narrative']
    # cache hit - no second HTTP call
    assert client.chat.completions.create.call_count == 1


@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_fresh_narrative_bypasses_an_existing_cache_entry(mock_openai_cls, tmp_path):
    cache_path = str(tmp_path / 'narrative.json')
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(json.dumps(_valid_llm_json()))
    mock_openai_cls.return_value = client

    metrics, tiers = _metrics(), _tier_rows()
    llm_insights.generate_narrative_with_guardrail(
        metrics, tiers, model='gpt-test', api_key='key', base_url='', cache_path=cache_path
    )
    assert client.chat.completions.create.call_count == 1

    llm_insights.generate_narrative_with_guardrail(
        metrics, tiers, model='gpt-test', api_key='key', base_url='', cache_path=cache_path,
        fresh=True
    )
    assert client.chat.completions.create.call_count == 2


@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_fallback_narrative_is_never_written_to_cache(mock_openai_cls, mock_sleep, tmp_path):
    cache_path = str(tmp_path / 'narrative.json')
    bad_shape = json.dumps({'headline': {}, 'risk': [], 'actions': []})
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(bad_shape)
    mock_openai_cls.return_value = client

    result = llm_insights.generate_narrative_with_guardrail(
        _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url='',
        cache_path=cache_path
    )

    assert result['status'] == llm_insights.BANNER_RETRIED_THEN_FALLBACK
    assert not os.path.exists(cache_path)


# === T3/T17 - narrative_review.json sidecar =================================

def test_review_sidecar_write_then_read_round_trips(tmp_path):
    path = str(tmp_path / 'narrative_review.json')
    ok = llm_insights.write_review_sidecar(
        path, llm_insights.BANNER_LLM_ACCEPTED, '2026-09-04T10:00:00', _valid_llm_json()
    )

    assert ok is True
    result = llm_insights.read_review_sidecar(path)
    assert result['guardrail_status'] == llm_insights.BANNER_LLM_ACCEPTED
    assert result['reviewed_at'] is None
    assert result['reviewed_by'] is None


def test_review_sidecar_updated_with_reviewed_at_and_by(tmp_path):
    path = str(tmp_path / 'narrative_review.json')
    llm_insights.write_review_sidecar(
        path, llm_insights.BANNER_LLM_ACCEPTED, '2026-09-04T10:00:00', _valid_llm_json()
    )
    llm_insights.write_review_sidecar(
        path, llm_insights.BANNER_LLM_ACCEPTED, '2026-09-04T10:00:00', _valid_llm_json(),
        reviewed_at='2026-09-04T11:00:00', reviewed_by='operator1'
    )

    result = llm_insights.read_review_sidecar(path)
    assert result['reviewed_at'] == '2026-09-04T11:00:00'
    assert result['reviewed_by'] == 'operator1'


def test_review_sidecar_write_failure_is_caught_and_logged_warning(tmp_path, monkeypatch):
    path = str(tmp_path / 'narrative_review.json')

    def failing_replace(*args, **kwargs):
        raise OSError('simulated disk full')

    monkeypatch.setattr('sosmed_sentiment.report.llm_insights.os.replace', failing_replace)

    messages, sink_id = _capture_logs()
    try:
        ok = llm_insights.write_review_sidecar(
            path, llm_insights.BANNER_LLM_ACCEPTED, '2026-09-04T10:00:00', _valid_llm_json()
        )
    finally:
        logger.remove(sink_id)

    assert ok is False
    assert any('narrative_review.json' in m for m in messages)


# === T12/T16 - message-content assertions (problem+cause+fix), not just level

@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_transport_failure_log_message_states_problem_cause_and_fix(mock_openai_cls, mock_sleep):
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception('connection refused')
    mock_openai_cls.return_value = client

    messages, sink_id = _capture_logs()
    try:
        llm_insights.generate_narrative_with_guardrail(
            _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
        )
    finally:
        logger.remove(sink_id)

    joined = '\n'.join(messages)
    # problem
    assert 'gagal' in joined
    # cause
    assert 'endpoint' in joined or 'timeout' in joined
    # fix
    assert 'cek .env' in joined or 'fallback' in joined


@patch('sosmed_sentiment.report.llm_insights.time.sleep')
@patch('sosmed_sentiment.report.llm_insights.OpenAI')
def test_guardrail_reject_log_message_names_the_failing_claim(mock_openai_cls, mock_sleep):
    bad_shape = json.dumps({'headline': {}, 'risk': [], 'actions': []})
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(bad_shape)
    mock_openai_cls.return_value = client

    messages, sink_id = _capture_logs()
    try:
        llm_insights.generate_narrative_with_guardrail(
            _metrics(), _tier_rows(), model='gpt-test', api_key='key', base_url=''
        )
    finally:
        logger.remove(sink_id)

    joined = '\n'.join(messages)
    assert 'ditolak' in joined or 'gagal' in joined
    assert 'fallback' in joined


# === Payload builder: never sends raw quotes (Decision #5) ==================

def test_payload_never_includes_raw_example_comment_text():
    payload = llm_insights.build_payload(_metrics(), _tier_rows())
    serialized = json.dumps(payload)
    assert 'komentar contoh' not in serialized
    assert 'text_raw' not in serialized
    assert 'username' not in serialized
