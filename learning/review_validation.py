"""Bounded, read-only checks of annotated editorial review samples.

Hashes establish self-consistency and comparison to the current bank, not the
identity or qualifications of the person who supplied a packet. Rebuilds use
separate SELECTs; freeze editorial changes before making an editorial decision.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import math
import re

from .content_review import (
    CARD_FIELDS, CHECKLIST_TEMPLATE, CONTENT_FIELDS, HUMAN_REVIEW_TEMPLATE,
    MAX_CONTENTS, MAX_ITEMS, MAX_PACKET_BYTES, OPTION_FIELDS, QUESTION_FIELDS,
    SCHEMA_VERSION, SELECTION_ORDER, build_review_packet,
)


REPORT_VERSION = 'linguapath-review-validation-v1'
CONCLUSIONS = ('pass', 'needs_changes', 'insufficient_info')
CHECK_RESULTS = ('pass', 'fail', 'not_applicable')
_HEX = re.compile(r'^[0-9a-f]{64}$')
_TOP_KEYS = {'schema_version', 'scope', 'approval_allowed', 'authority_notice',
    'selection', 'checklist_template', 'human_review', 'contents', 'fingerprint', 'generated_at'}
_SOURCE_KEYS = {'content', 'flashcards', 'questions', 'coverage', 'content_hash',
    'structural_findings', 'findings_scope'}
_ID_MAX = 2**63 - 1
MAX_PROBLEMS = 200


class ReviewPacketLoadError(ValueError):
    """The upload cannot be interpreted as a bounded JSON review packet."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReviewPacketLoadError('JSON contains duplicate object keys.')
        result[key] = value
    return result


def _reject_constant(value):
    raise ReviewPacketLoadError('JSON must not contain non-finite numbers.')


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ReviewPacketLoadError('JSON must not contain non-finite numbers.')
    return parsed


def load_review_packet(stream):
    """Read at most 20 MiB + one byte from a file/upload; never close it."""
    try:
        raw = stream.read(MAX_PACKET_BYTES + 1)
        if not isinstance(raw, (bytes, str)):
            raise ReviewPacketLoadError('Review packet must be UTF-8 JSON.')
        if len(raw) > MAX_PACKET_BYTES:
            raise ReviewPacketLoadError('Review packet exceeds 20 MiB.')
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        if len(raw.encode('utf-8')) > MAX_PACKET_BYTES:
            raise ReviewPacketLoadError('Review packet exceeds 20 MiB.')
        return json.loads(raw, object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant, parse_float=_finite_float)
    except ReviewPacketLoadError:
        raise
    except (AttributeError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ReviewPacketLoadError('Review packet must be valid UTF-8 JSON.') from error


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _is_id(value):
    return type(value) is int and 0 < value <= _ID_MAX


def _date_valid(value):
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            date.fromisoformat(value)
            return True
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except (ValueError, OverflowError):
        return False


def _bounded_json(value):
    # An API caller can supply objects not produced by the bounded loader. Reject
    # cycles, extreme nesting, unknown Python objects and non-finite values too.
    stack = [(value, 0)]
    containers = set()
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > 16 or nodes > 400000:
            return False
        if type(current) in (dict, list):
            if id(current) in containers:
                return False
            containers.add(id(current))
            if len(current) + nodes > 400000:
                return False
            if type(current) is dict:
                if any(type(key) is not str for key in current):
                    return False
                stack.extend((child, depth + 1) for child in current.values())
            else:
                stack.extend((child, depth + 1) for child in current)
        elif type(current) not in (str, int, bool, float, type(None)):
            return False
    try:
        return len(_encoded(value)) <= MAX_PACKET_BYTES
    except (ValueError, UnicodeError, OverflowError, RecursionError):
        return False


def validate_review_packet(packet):
    """Return source status and annotation completeness without writing to DB.

    A valid unfinished draft has status ``current`` and incomplete annotations.
    A self-consistent old export has status ``stale``. ``invalid`` means its
    shape, annotations, or original normalized fingerprint cannot be verified.
    Recomputed attacker-controlled hashes cannot prove authentic provenance.
    """
    report = {'version': REPORT_VERSION, 'status': 'invalid', 'source_matches': False,
        'annotations_complete': False, 'approval_allowed': False,
        'sample_covers_all_selected_sources': False,
        'summary': {'items_total': 0, 'items_complete': 0, 'items_pending': 0,
            'checklist_total': 0, 'checklist_completed': 0,
            'conclusions': {key: 0 for key in (*CONCLUSIONS, 'pending')},
            'packet_reviewer_complete': False},
        'items': [], 'problems': [], 'problems_truncated': False,
        'notice': 'Read-only comparison; hashes do not verify reviewer identity or qualifications. No approval or publication. Freeze editorial changes and recheck before a decision.'}
    invalid = False

    def problem(path, code, message, *, malformed=True):
        nonlocal invalid
        invalid |= malformed
        if len(report['problems']) < MAX_PROBLEMS:
            report['problems'].append({'path': path, 'code': code, 'message': message})
        else:
            report['problems_truncated'] = True

    def keys(value, expected, path):
        if type(value) is not dict or set(value) != set(expected):
            problem(path, 'invalid_shape', 'Object fields do not match the review schema.')
            return False
        return True

    def review(value, path):
        if not keys(value, HUMAN_REVIEW_TEMPLATE, path):
            return False
        valid = True
        for key, limit in (('reviewer_name', 200), ('qualifications', 2000), ('notes', 4000)):
            if not isinstance(value[key], str) or len(value[key]) > limit:
                problem(f'{path}.{key}', 'invalid_annotation', 'Annotation text is invalid or exceeds its limit.')
                valid = False
        conclusion = value['conclusion']
        if conclusion is not None and (not isinstance(conclusion, str) or conclusion not in CONCLUSIONS):
            problem(f'{path}.conclusion', 'invalid_conclusion', 'Use pass, needs_changes, insufficient_info, or null.')
            valid = False
        reviewed_at = value['reviewed_at']
        if reviewed_at is not None and not _date_valid(reviewed_at):
            problem(f'{path}.reviewed_at', 'invalid_review_date', 'Use an ISO date or a timezone-aware ISO datetime.')
            valid = False
        if not valid:
            return False
        complete = all(value[key].strip() for key in ('reviewer_name', 'qualifications')) and reviewed_at is not None and conclusion is not None
        if conclusion in ('needs_changes', 'insufficient_info') and not value['notes'].strip():
            problem(f'{path}.notes', 'missing_conclusion_notes', 'Explain a needs_changes or insufficient_info conclusion.', malformed=False)
            complete = False
        return bool(complete)

    def checklist(value, path, conclusion):
        if not keys(value, CHECKLIST_TEMPLATE, path):
            return False
        complete, has_failure = True, False
        for name in CHECKLIST_TEMPLATE:
            entry = value[name]
            report['summary']['checklist_total'] += 1
            if not keys(entry, ('result', 'notes'), f'{path}.{name}'):
                complete = False
                continue
            result, notes = entry['result'], entry['notes']
            if result is not None and (not isinstance(result, str) or result not in CHECK_RESULTS):
                problem(f'{path}.{name}.result', 'invalid_check_result', 'Use pass, fail, not_applicable, or null.')
                complete = False
                continue
            if not isinstance(notes, str) or len(notes) > 4000:
                problem(f'{path}.{name}.notes', 'invalid_annotation', 'Checklist notes are invalid or exceed 4000 characters.')
                complete = False
                continue
            done = result is not None
            if result in ('fail', 'not_applicable') and not notes.strip():
                problem(f'{path}.{name}.notes', 'missing_check_notes', 'Explain failed or not-applicable checks.', malformed=False)
                done = False
            report['summary']['checklist_completed'] += int(done)
            complete &= done
            has_failure |= result == 'fail'
        if conclusion == 'pass' and has_failure:
            problem(path, 'conflicting_conclusion', 'A pass conclusion conflicts with a failed checklist entry.')
            complete = False
        return bool(complete)

    if not _bounded_json(packet):
        problem('$', 'invalid_json_value', 'Packet is oversized, too deeply nested, cyclic, or not finite JSON.')
        return report
    if not keys(packet, _TOP_KEYS, '$'):
        return report
    if (packet['schema_version'] != SCHEMA_VERSION or packet['scope'] != 'sample_for_human_review'
            or packet['approval_allowed'] is not False):
        problem('$', 'unsupported_scope', 'Only versioned non-approval review samples are supported.')
    if packet['checklist_template'] != CHECKLIST_TEMPLATE:
        problem('checklist_template', 'changed_template', 'The checklist template must remain unchanged.')
    if not _date_valid(packet['generated_at']):
        problem('generated_at', 'invalid_generation_date', 'Packet generation date is invalid.')
    if not isinstance(packet['authority_notice'], str):
        problem('authority_notice', 'invalid_shape', 'Authority notice must remain text.')
    if not isinstance(packet['fingerprint'], str) or not _HEX.fullmatch(packet['fingerprint']):
        problem('fingerprint', 'invalid_fingerprint', 'Packet fingerprint must be a SHA-256 hex digest.')
    selection = packet['selection']
    if not keys(selection, ('content_ids', 'max_items_per_kind_per_content', 'order'), 'selection'):
        return report
    ids, maximum = selection['content_ids'], selection['max_items_per_kind_per_content']
    if (type(ids) is not list or not 1 <= len(ids) <= MAX_CONTENTS or any(not _is_id(pk) for pk in ids)
            or ids != sorted(set(ids)) or type(maximum) is not int or not 1 <= maximum <= MAX_ITEMS
            or selection['order'] != SELECTION_ORDER):
        problem('selection', 'invalid_selection', 'Select 1–10 unique ascending positive content IDs and 1–100 items per kind.')
        return report
    records = packet['contents']
    if type(records) is not list or len(records) != len(ids):
        problem('contents', 'invalid_shape', 'One content record is required per selected ID.')
        return report
    report['summary']['packet_reviewer_complete'] = review(packet['human_review'], 'human_review')
    normalized = deepcopy(packet)
    normalized.pop('fingerprint')
    normalized.pop('generated_at')
    normalized['human_review'] = deepcopy(HUMAN_REVIEW_TEMPLATE)
    complete_coverage = True
    seen_items = {'flashcards': set(), 'questions': set()}
    for index, record in enumerate(records):
        path = f'contents[{index}]'
        if not keys(record, _SOURCE_KEYS, path):
            continue
        content = record['content']
        if not keys(content, CONTENT_FIELDS, f'{path}.content'):
            continue
        if type(content['id']) is not int or content['id'] != ids[index]:
            problem(f'{path}.content.id', 'wrong_parent', 'Content identity must match the ordered selection.')
        for name in CONTENT_FIELDS:
            value = content[name]
            if name in ('id', 'difficulty', 'estimated_minutes'):
                valid = type(value) is int and 0 <= value <= _ID_MAX
            elif name == 'is_published':
                valid = type(value) is bool
            elif name in ('reviewed_at', 'source_checked_on'):
                valid = value is None or _date_valid(value)
            else:
                valid = isinstance(value, str)
            if not valid:
                problem(f'{path}.content.{name}', 'invalid_source_field', 'Source field has an invalid type.')
        if not isinstance(record['content_hash'], str) or not _HEX.fullmatch(record['content_hash']):
            problem(f'{path}.content_hash', 'invalid_source_hash', 'Content hash must be a SHA-256 hex digest.')
        if not keys(record['coverage'], ('flashcards', 'questions'), f'{path}.coverage'):
            continue
        if not isinstance(record['findings_scope'], str) or type(record['structural_findings']) is not list:
            problem(path, 'invalid_findings', 'Source findings must retain their original schema.')
        for kind, field_names in (('flashcards', CARD_FIELDS), ('questions', QUESTION_FIELDS)):
            items, coverage = record[kind], record['coverage'][kind]
            if (type(items) is not list or len(items) > maximum
                    or not keys(coverage, ('total', 'exported', 'complete'), f'{path}.coverage.{kind}')):
                problem(f'{path}.{kind}', 'invalid_sample', 'Sample exceeds its selected bound or has invalid coverage.')
                continue
            if (type(coverage['total']) is not int or coverage['total'] < len(items)
                    or type(coverage['exported']) is not int or coverage['exported'] != len(items)
                    or type(coverage['complete']) is not bool or coverage['complete'] != (len(items) == coverage['total'])):
                problem(f'{path}.coverage.{kind}', 'invalid_coverage', 'Coverage counts do not match exported items.')
            complete_coverage &= coverage['complete'] is True
            for offset, item in enumerate(items):
                item_path = f'{path}.{kind}[{offset}]'
                expected = set(field_names) | {'version_hash', 'human_review', 'checklist'}
                if kind == 'questions':
                    expected.add('options')
                if not keys(item, expected, item_path):
                    continue
                if not _is_id(item['id']) or item['id'] in seen_items[kind] or type(item['content_id']) is not int or item['content_id'] != ids[index]:
                    problem(item_path, 'invalid_item_identity', 'Item IDs must be unique and belong to their selected content.')
                else:
                    seen_items[kind].add(item['id'])
                for name in field_names:
                    if name in ('id', 'content_id', 'order'):
                        valid = type(item[name]) is int and 0 <= item[name] <= _ID_MAX
                    elif name == 'is_available':
                        valid = type(item[name]) is bool
                    else:
                        valid = isinstance(item[name], str)
                    if not valid:
                        problem(f'{item_path}.{name}', 'invalid_source_field', 'Source field has an invalid type.')
                if kind == 'questions':
                    options = item['options']
                    if type(options) is not list or len(options) > 100:
                        problem(f'{item_path}.options', 'invalid_options', 'Question options must be a bounded list.')
                    else:
                        option_ids = set()
                        for number, option in enumerate(options):
                            option_path = f'{item_path}.options[{number}]'
                            if not keys(option, OPTION_FIELDS, option_path):
                                continue
                            if (not _is_id(option['id']) or option['id'] in option_ids or type(option['question_id']) is not int
                                    or option['question_id'] != item['id'] or type(option['is_correct']) is not bool
                                    or any(not isinstance(option[key], str) for key in ('label', 'text', 'explanation_vi'))):
                                problem(option_path, 'invalid_option', 'Option identity or field types are invalid.')
                            if _is_id(option['id']):
                                option_ids.add(option['id'])
                source_item = {key: value for key, value in item.items() if key not in ('version_hash', 'human_review', 'checklist')}
                if item['version_hash'] != _hash(source_item):
                    problem(f'{item_path}.version_hash', 'item_hash_mismatch', 'Item evidence no longer matches its recorded hash.')
                reviewer_complete = review(item['human_review'], f'{item_path}.human_review')
                conclusion = item['human_review'].get('conclusion') if type(item['human_review']) is dict else None
                checks_complete = checklist(item['checklist'], f'{item_path}.checklist', conclusion)
                complete = reviewer_complete and checks_complete
                summary = report['summary']
                summary['items_total'] += 1
                summary['items_complete'] += int(complete)
                summary['items_pending'] += int(not complete)
                if conclusion is None or isinstance(conclusion, str) and conclusion in CONCLUSIONS:
                    summary['conclusions'][conclusion or 'pending'] += 1
                report['items'].append({'path': item_path, 'kind': kind, 'id': item['id'] if _is_id(item['id']) else None,
                    'content_id': ids[index], 'complete': complete, 'conclusion': conclusion if isinstance(conclusion, str) and conclusion in CONCLUSIONS else None})
                clean_item = normalized['contents'][index][kind][offset]
                clean_item['human_review'] = deepcopy(HUMAN_REVIEW_TEMPLATE)
                clean_item['checklist'] = deepcopy(CHECKLIST_TEMPLATE)
    if packet['fingerprint'] != _hash(normalized):
        problem('fingerprint', 'packet_hash_mismatch', 'Immutable packet evidence does not match its original normalized fingerprint.')
    packet_conclusion = packet['human_review'].get('conclusion') if type(packet['human_review']) is dict else None
    if packet_conclusion == 'pass' and any(report['summary']['conclusions'][key] for key in ('needs_changes', 'insufficient_info')):
        problem('human_review.conclusion', 'conflicting_conclusion', 'A packet pass conflicts with an item requiring changes or more information.')
    if invalid:
        return report
    report['sample_covers_all_selected_sources'] = bool(complete_coverage)
    # The shared header is an optional convenience. Each item's own reviewer
    # fields are required independently, so copying shared fields is explicit.
    report['annotations_complete'] = bool(report['summary']['items_total'] and not report['summary']['items_pending'])
    try:
        current = build_review_packet(ids, max_items=maximum)
    except ValueError:
        problem('contents', 'source_unavailable', 'One or more selected sources are missing or cannot be exported within the bound.', malformed=False)
        report['status'] = 'stale'
        return report
    current.pop('fingerprint')
    current.pop('generated_at')
    # JSON evidence comparison must distinguish booleans, integers and floats;
    # Python object equality alone treats e.g. True and 1 as interchangeable.
    source_matches = _hash(normalized) == _hash(current)
    report['source_matches'] = source_matches
    report['status'] = 'current' if source_matches else 'stale'
    if not source_matches:
        problem('contents', 'source_changed', 'Current source evidence differs from this self-consistent snapshot; export a new sample and review affected items.', malformed=False)
    return report
