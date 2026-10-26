"""Pack model evidence without truncating structured question essentials."""
import json
from dataclasses import dataclass


MAX_CONTEXT_CHARS = 5400
CONTEXT_VERSION = 'question-essentials-v1'
SEPARATOR = '\n\n---\n\n'


@dataclass
class PackedContext:
    text: str
    evidence: list
    sufficient: bool


def _question_essentials(item):
    data = item['structured']
    required = ('prompt', 'passage', 'audio_script', 'transcript', 'explanation', 'explanation_vi')
    if not all(isinstance(data.get(key), str) for key in required):
        raise ValueError('Incomplete question fields')
    options = data.get('options')
    if not data['prompt'].strip() or not isinstance(options, list) or len(options) < 2:
        raise ValueError('Incomplete question')
    if any(not isinstance(option, dict) or
           not all(isinstance(option.get(key), str) for key in ('label', 'text', 'explanation_vi')) or
           not option['label'].strip() or not option['text'].strip() or
           not isinstance(option.get('is_correct'), bool) for option in options):
        raise ValueError('Incomplete options')
    if sum(option['is_correct'] for option in options) != 1:
        raise ValueError('Invalid answer key')
    essential = {'source': item['source'], 'prompt': data['prompt'], 'options': options,
                 'explanation_vi': data['explanation_vi']}
    if data['explanation'].strip() != data['explanation_vi'].strip():
        essential['explanation'] = data['explanation']
    return json.dumps(essential, ensure_ascii=False, separators=(',', ':'))


def pack_evidence(evidence, max_chars=MAX_CONTEXT_CHARS):
    """Reserve essentials first, then use remaining space for stimulus.

    Legacy text is explicitly identified as unstructured; its completeness does
    not stand in for a structured question. Oversized legacy questions fail
    closed because their answer/explanation positions are unknown.
    """
    if not evidence or max_chars < 1:
        return PackedContext('', [], False)
    blocks, selected, optional = [], [], []
    for item in evidence:
        record = dict(item)
        structured = item.get('structured')
        if item.get('kind') == 'question' and 'structured' in item and not isinstance(structured, dict):
            return PackedContext('', [], False)
        if item.get('kind') == 'question' and isinstance(structured, dict):
            try:
                block = _question_essentials(item)
            except (KeyError, TypeError, ValueError):
                return PackedContext('', [], False)
            record.update(context_format='structured_question', context_complete=True)
            seen = set()
            stimulus = []
            for key in ('passage', 'audio_script', 'transcript'):
                text = structured[key].strip()
                normalized = ' '.join(text.split())
                if text and normalized not in seen:
                    seen.add(normalized)
                    stimulus.append((key, text))
            optional.append((len(blocks), stimulus))
        else:
            text = str(item.get('text', '')).strip()
            if not text:
                continue
            block = 'Legacy source (unstructured):\n' + text
            record.update(context_format='legacy_text', context_complete=False)
        blocks.append(block)
        selected.append(record)

    if not blocks:
        return PackedContext('', [], False)
    size = sum(map(len, blocks)) + len(SEPARATOR) * (len(blocks) - 1)
    if size > max_chars:
        # Never silently cut a question's essentials. Other legacy sources may
        # be excerpted, with an explicit label and only included sources cited.
        if any(item.get('kind') == 'question' for item in selected):
            return PackedContext('', [], False)
        excerpt_blocks, excerpt_sources = [], []
        remaining = max_chars
        marker = '\n[Legacy source excerpt; remaining text omitted.]'
        for block, item in zip(blocks, selected):
            available = remaining - (len(SEPARATOR) if excerpt_blocks else 0)
            if available <= len(marker):
                break
            part = block if len(block) <= available else block[:available - len(marker)] + marker
            excerpt_blocks.append(part)
            excerpt_sources.append(item)
            remaining -= len(part) + (len(SEPARATOR) if len(excerpt_blocks) > 1 else 0)
        return PackedContext(SEPARATOR.join(excerpt_blocks), excerpt_sources, bool(excerpt_blocks))

    remaining = max_chars - size
    stimulus_blocks = []
    for index, stimulus in optional:
        for key, text in stimulus:
            label = f'\nStimulus for source {index + 1} / {key}: '
            marker = '\n[Stimulus excerpt; remaining text omitted.]'
            if remaining <= len(label) + len(marker):
                selected[index]['context_complete'] = False
                continue
            if len(label) + len(text) <= remaining:
                addition = label + text
            else:
                addition = label + text[:remaining - len(label) - len(marker)] + marker
                selected[index]['context_complete'] = False
            stimulus_blocks.append(addition)
            remaining -= len(addition)
    return PackedContext(SEPARATOR.join(blocks) + ''.join(stimulus_blocks), selected, True)
