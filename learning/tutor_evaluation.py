"""Bounded public-context Tutor runs; structural metrics never grade answer quality.

Offline is the default and uses the real answer pipeline with inference disabled.
Live runs need an explicit small cap and an existing active staff principal; the
ordinary per-user/global quota is still enforced inside that pipeline.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from time import perf_counter

from django.utils import timezone


VERSION = 'linguapath-tutor-evaluation-v1'
DEFAULT_CASES = Path(__file__).resolve().parent / 'data' / 'tutor_router_regression_v1.json'
MAX_FIXTURE_BYTES = 1024 * 1024
MAX_CASES = 50
MAX_LIVE_CALLS = 10
MAX_RESULT_BYTES = 128 * 1024
MAX_SNAPSHOT_BYTES = 512 * 1024
MODES = frozenset(('retrieval_only', 'no_match', 'needs_context', 'llm_rag',
                  'context_insufficient', 'budget_limited', 'retrieval_fallback'))


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _unique_pairs(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError('Evaluation JSON contains duplicate keys.')
        data[key] = value
    return data


def _not_finite(value):
    raise ValueError('Evaluation JSON must contain finite numbers.')


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        _not_finite(value)
    return parsed


def _text(value, limit):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _expected_identity(source):
    if type(source) is not dict:
        raise ValueError('Expected sources must be objects.')
    kind = source.get('kind')
    field = 'knowledge_id' if kind == 'knowledge' else 'term' if kind == 'flashcard' else None
    if field is None or set(source) != {'kind', field} or not _text(source.get(field), 200):
        raise ValueError('Expected sources require a knowledge ID or vocabulary headword.')
    value = source[field].strip()
    return (kind, value.casefold() if kind == 'flashcard' else value)


def validate_evaluation_cases(fixture):
    """Validate the complete fixture before the first answer or live request."""
    if (type(fixture) is not dict or set(fixture) != {'version', 'provenance', 'cases'}
            or not _text(fixture.get('version'), 100) or not _text(fixture.get('provenance'), 2000)):
        raise ValueError('Fixture requires version, provenance and cases only.')
    cases = fixture['cases']
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError('Select from 1 to 50 evaluation cases.')
    seen = set()
    for row in cases:
        if (type(row) is not dict or not {'id', 'category', 'query', 'expected'} <= set(row)
                or set(row) - {'id', 'category', 'query', 'expected', 'note'}
                or not _text(row.get('id'), 100) or row['id'] in seen
                or not _text(row.get('query'), 500) or not _text(row.get('category'), 80)
                or ('note' in row and (not isinstance(row['note'], str) or len(row['note']) > 2000))
                or type(row.get('expected')) is not list or len(row['expected']) > 10):
            raise ValueError('Case identity, query, category or expected sources are invalid.')
        seen.add(row['id'])
        sources = [_expected_identity(source) for source in row['expected']]
        if len(set(sources)) != len(sources):
            raise ValueError('Expected source identities must not repeat.')
    try:
        if len(_encoded(fixture)) > MAX_FIXTURE_BYTES:
            raise ValueError('Evaluation fixture exceeds 1 MiB.')
    except (TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError('Evaluation fixture must be finite UTF-8 JSON.') from error
    return fixture


def load_evaluation_cases(path=DEFAULT_CASES):
    """Load strict UTF-8 JSON, bounded before parsing and before any DB work."""
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_FIXTURE_BYTES + 1)
        if len(raw) > MAX_FIXTURE_BYTES:
            raise ValueError('Evaluation fixture exceeds 1 MiB.')
        fixture = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs,
                             parse_constant=_not_finite, parse_float=_finite_float)
        return validate_evaluation_cases(fixture)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError('Evaluation fixture must be valid bounded UTF-8 JSON.') from error


def _json_copy(value, byte_limit, *, node_limit=50000):
    stack, nodes = [(value, 0, frozenset())], 0
    while stack:
        current, depth, ancestors = stack.pop()
        nodes += 1
        if depth > 16 or nodes > node_limit:
            raise ValueError('Evaluation result is too deeply nested or too large.')
        if type(current) in (dict, list):
            if id(current) in ancestors:
                raise ValueError('Evaluation result contains cyclic containers.')
            child_ancestors = ancestors | {id(current)}
            if type(current) is dict:
                if any(type(key) is not str for key in current):
                    raise ValueError('Evaluation object keys must be text.')
                stack.extend((child, depth + 1, child_ancestors) for child in current.values())
            else:
                stack.extend((child, depth + 1, child_ancestors) for child in current)
        elif type(current) not in (str, int, bool, float, type(None)):
            raise ValueError('Evaluation result is not JSON.')
    raw = _encoded(value)
    if len(raw) > byte_limit:
        raise ValueError('Evaluation result exceeds its byte limit.')
    return json.loads(raw)


def _safe_result(raw):
    if (type(raw) is not dict or raw.get('mode') not in MODES
            or not _text(raw.get('answer'), 60000)
            or type(raw.get('sources')) is not list or len(raw['sources']) > 10
            or any(not isinstance(value, str) or len(value) > 2000 for value in raw['sources'])
            or type(raw.get('evidence_sources')) is not list or len(raw['evidence_sources']) > 10
            or type(raw.get('generation')) is not dict):
        raise ValueError('Tutor result is malformed.')
    # Persist only production response fields, never arbitrary adapter headers,
    # exceptions, user records or credential-like additions from an integration.
    result = {key: raw[key] for key in ('answer', 'sources', 'mode')}
    source_fields = {'title', 'href', 'kind', 'label', 'review_status', 'meaning_vi',
                     'source_ref', 'context_format', 'context_complete'}
    result['evidence_sources'] = []
    for source in raw['evidence_sources']:
        if type(source) is not dict or any(not isinstance(source.get(key, ''), str)
                for key in ('title', 'href', 'kind', 'label', 'review_status', 'meaning_vi')):
            raise ValueError('Tutor evidence card is malformed.')
        result['evidence_sources'].append({key: value for key, value in source.items() if key in source_fields})
    generation_fields = {'provider', 'model', 'prompt_version', 'context_version', 'generated_at',
                         'attempted_provider', 'attempted_model', 'bridge_prompt_version', 'requested_model'}
    result['generation'] = {key: value for key, value in raw['generation'].items() if key in generation_fields}
    for key, value in result['generation'].items():
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            raise ValueError('Tutor generation metadata is malformed.')
    if 'provider' in raw:
        if not isinstance(raw['provider'], str) or len(raw['provider']) > 40:
            raise ValueError('Tutor provider metadata is malformed.')
        result['provider'] = raw['provider']
    if 'clarification_prompts' in raw:
        values = raw['clarification_prompts']
        if type(values) is not list or len(values) > 10 or any(not _text(value, 2000) for value in values):
            raise ValueError('Tutor clarification prompts are malformed.')
        result['clarification_prompts'] = values
    return _json_copy(result, MAX_RESULT_BYTES)


def _actual_identities(result):
    actual = set()
    for index, source in enumerate(result['evidence_sources']):
        kind = source.get('kind')
        ref = source.get('source_ref')
        if kind == 'knowledge' and type(ref) is dict and _text(ref.get('object_id'), 200):
            actual.add(('knowledge', ref['object_id'].strip()))
        elif kind == 'flashcard' and _text(source.get('label'), 200):
            # This is headword coverage, not sense correctness or faithfulness.
            actual.add(('flashcard', source['label'].strip().casefold()))
        else:
            actual.add((str(kind or 'unknown'), f'unrecognized-source-{index}'))
    return actual


def _latencies(values):
    ordered = sorted(values)
    return {'count': len(ordered), 'median': round(median(ordered), 3) if ordered else None,
            'p95': round(ordered[math.ceil(.95 * len(ordered)) - 1], 3) if ordered else None}


def run_tutor_evaluation(fixture, *, exam='TOEIC', live=False, user=None,
                         max_live_calls=0, answerer=None):
    """Run one request per case, without retries, sleeps or quota overrides.

    Timing covers the entire local answer pipeline. Mode-derived model attempt
    counts are not provider billing measurements. A human must independently
    judge answer quality and the default editorial fixture is not a holdout.
    ``answerer`` is a trusted dependency-injection hook for unit tests only.
    """
    validate_evaluation_cases(fixture)
    if type(live) is not bool or exam not in ('TOEIC', 'IELTS'):
        raise ValueError('Execution mode or exam is invalid.')
    if type(max_live_calls) is not int:
        raise ValueError('Live cap must be an explicit integer.')
    if live:
        if (not 1 <= max_live_calls <= MAX_LIVE_CALLS or len(fixture['cases']) > max_live_calls
                or not getattr(user, 'is_active', False) or not getattr(user, 'is_staff', False)
                or not getattr(user, 'is_authenticated', False)
                or type(getattr(user, 'pk', None)) is not int or user.pk < 1):
            raise ValueError('Live runs require an active staff user and a cap of 1–10 covering every case.')
    elif max_live_calls != 0:
        raise ValueError('A live cap is only valid with explicit live execution.')
    if answerer is None:
        from .ai import answer_tutor_question
        answerer = answer_tutor_question
    cases, modes, all_times, model_times = [], Counter(), [], []
    errors = attempts = model_answers = exact = covered = expected_count = negatives = abstained = 0
    for row in fixture['cases']:
        expected = {_expected_identity(source) for source in row['expected']}
        captured, observer_calls = {}, 0

        def observe(evidence, packed):
            nonlocal observer_calls
            observer_calls += 1
            try:
                packed_value = None if packed is None else {
                    'text': packed.text, 'sufficient': packed.sufficient,
                    'sources': [{key: item[key] for key in ('source_ref', 'context_format', 'context_complete') if key in item}
                                for item in packed.evidence]}
                value = _json_copy({'retrieved': evidence, 'packed': packed_value}, MAX_SNAPSHOT_BYTES)
                captured['snapshot'] = {**value, 'sha256': _hash(value)}
            except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
                captured['invalid'] = True

        start = perf_counter()
        result, error = None, None
        try:
            raw = answerer(row['query'], exam=exam, user=user if live else None, use_ai=live,
                           public_context_only=True, evidence_observer=observe)
            try:
                result = _safe_result(raw)
            except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
                error = 'invalid_result'
            if captured.get('invalid') or observer_calls > 1:
                error = 'invalid_evidence_snapshot'
                result = None
        except Exception:
            # The caller receives no provider exception text, tokens or traces.
            error = 'case_execution_failed'
        elapsed = round(max(0, (perf_counter() - start) * 1000), 3)
        all_times.append(elapsed)
        actual = _actual_identities(result) if result is not None else set()
        mode = result['mode'] if result else 'error'
        modes[mode] += 1
        errors += int(error is not None)
        mode_attempt = mode in ('llm_rag', 'retrieval_fallback')
        attempts += int(mode_attempt)
        model_answers += int(mode == 'llm_rag')
        if mode == 'llm_rag':
            model_times.append(elapsed)
        source_exact = error is None and expected == actual
        exact += int(source_exact)
        covered += len(expected & actual)
        expected_count += len(expected)
        negatives += int(not expected)
        abstained += int(not expected and mode == 'no_match' and not actual and error is None)
        cases.append({'id': row['id'], 'category': row['category'], 'query': row['query'],
            'expected': sorted(expected), 'actual': sorted(actual), 'source_exact_match': source_exact,
            'omissions': sorted(expected - actual), 'false_positives': sorted(actual - expected),
            'elapsed_ms': elapsed, 'error': error, 'result': result,
            'evidence_snapshot': captured.get('snapshot') if error is None else None,
            'snapshot_notice': 'observed' if observer_calls == 1 and error is None else 'not_observed'})
    count = len(cases)
    return {'version': VERSION, 'generated_at': timezone.now().isoformat(), 'exam': exam,
        'scope': 'Public-context answer-pipeline evaluation. Source identity checks are structural, not semantic quality, sense accuracy, injection resistance or independent human adjudication. The default fixture is a known AI-editorial regression, not an independent holdout.',
        'public_context_only': True,
        'fixture': {'version': fixture['version'], 'provenance': fixture['provenance'], 'sha256': _hash(fixture)},
        'execution': {'mode': 'live' if live else 'offline', 'public_context_only': True,
            'max_live_calls': max_live_calls,
            'use_ai_requests': count if live else 0, 'model_attempts_inferred_from_mode': attempts,
            'model_answers': model_answers,
            'notice': 'Mode-derived counts are not provider usage or cost. Local elapsed time includes retrieval and quota work; offline times are not model inference latency.'},
        'summary': {'cases': count, 'errors': errors, 'mode_counts': dict(sorted(modes.items())),
            'source_exact_matches': exact, 'source_exact_match_rate': round(exact / count, 4),
            'expected_sources': expected_count, 'covered_expected_sources': covered,
            'source_coverage': round(covered / expected_count, 4) if expected_count else None,
            'negative_cases': negatives, 'negative_abstentions': abstained,
            'negative_abstention_rate': round(abstained / negatives, 4) if negatives else None,
            'latency_ms': {'all': _latencies(all_times), 'model_answers': _latencies(model_times)}},
        'cases': cases}
