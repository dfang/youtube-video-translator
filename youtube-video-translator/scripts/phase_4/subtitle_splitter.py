import json
import re
import sys
from datetime import timedelta
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))


DEFAULT_MAX_DURATION = 6.0
DEFAULT_TARGET_DURATION = 4.0
DEFAULT_MAX_CHARS = 28
DEFAULT_MAX_CPS = 15.0
DEFAULT_MIN_DURATION = 0.8
MIN_TEXT_WEIGHT = 1.0
CLAUSE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;：:])\s*|(?<=[，、,])\s*")
SECONDARY_SPLIT_RE = re.compile(
    r"(?<=\s)(?:and|but|or|so|because|that|which|who|when|while|if|then)\s+",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?")


def srt_time_to_delta(srt_time):
    srt_time = srt_time.replace(".", ",")
    h, m, s_ms = srt_time.split(":")
    s, ms = s_ms.split(",")
    return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))


def delta_to_srt_time(delta):
    total_seconds = max(0.0, delta.total_seconds())
    whole_seconds = int(total_seconds)
    milliseconds = int(round((total_seconds - whole_seconds) * 1000))
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    hours = whole_seconds // 3600
    minutes = (whole_seconds % 3600) // 60
    seconds = whole_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def protect_abbreviations(text):
    abbreviations = [
        r"Mr\.",
        r"Mrs\.",
        r"Dr\.",
        r"St\.",
        r"U\.S\.",
        r"U\.K\.",
        r"i\.e\.",
        r"e\.g\.",
    ]
    protected = text
    placeholders = {}
    for i, pattern in enumerate(abbreviations):
        token = f"__ABBR_{i}__"
        protected = re.sub(pattern, token, protected)
        placeholders[token] = pattern.replace("\\", "")
    return protected, placeholders


def restore_abbreviations(text, placeholders):
    restored = text
    for token, value in placeholders.items():
        restored = restored.replace(token, value)
    return restored


def normalize_text(text):
    return " ".join(text.split()).strip()


def is_cjk(char):
    return bool(re.match(r"[\u4e00-\u9fff]", char))


def smart_join(left, right):
    left = normalize_text(left)
    right = normalize_text(right)
    if not left:
        return right
    if not right:
        return left

    left_char = left[-1]
    right_char = right[0]
    if is_cjk(left_char) or is_cjk(right_char):
        return f"{left}{right}"
    if re.match(r"[A-Za-z0-9,.;:!?)]", left_char) and re.match(r"[A-Za-z0-9(\"']", right_char):
        return f"{left} {right}"
    return f"{left}{right}"


def text_display_units(text):
    units = 0.0
    for char in text:
        if char.isspace():
            continue
        if re.match(r"[\u4e00-\u9fff]", char):
            units += 1.0
        elif re.match(r"[A-Za-z0-9]", char):
            units += 0.55
        else:
            units += 0.35
    return max(MIN_TEXT_WEIGHT, units)


def tokenize_for_alignment(text):
    return TOKEN_RE.findall(text or "")


def token_weight(text):
    tokens = tokenize_for_alignment(text)
    if tokens:
        return len(tokens)
    return max(1, int(round(text_display_units(text))))


def load_word_timing_sidecar(input_path):
    sidecar_path = Path(input_path).with_suffix(".word_timestamps.json")
    if not sidecar_path.exists():
        return {}
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    segments = {}
    for seg in payload.get("segments", []):
        index = seg.get("index")
        words = seg.get("words")
        if not isinstance(index, int) or not isinstance(words, list):
            continue
        valid_words = []
        for word in words:
            text = normalize_text(word.get("text", ""))
            start = word.get("start")
            end = word.get("end")
            if not text or start is None or end is None:
                continue
            try:
                valid_words.append({
                    "text": text,
                    "start": float(start),
                    "end": float(end),
                })
            except (TypeError, ValueError):
                continue
        if valid_words:
            segments[index] = {
                "text": normalize_text(seg.get("text", "")),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "words": valid_words,
            }
    return segments


def split_into_clauses(text):
    protected, placeholders = protect_abbreviations(text)
    parts = CLAUSE_SPLIT_RE.split(protected)
    clauses = []
    for part in parts:
        normalized = normalize_text(restore_abbreviations(part, placeholders))
        if normalized:
            clauses.append(normalized)
    return clauses


def split_clause_by_connectors(text):
    parts = SECONDARY_SPLIT_RE.split(text)
    if len(parts) <= 1:
        return [text]
    clauses = [normalize_text(part) for part in parts if normalize_text(part)]
    return clauses or [text]


def split_long_text_by_units(text, max_units):
    normalized = normalize_text(text)
    if not normalized:
        return [""]
    if text_display_units(normalized) <= max_units:
        return [normalized]

    tokens = re.findall(r"\S+\s*", normalized)
    if not tokens:
        return [normalized]

    pieces = []
    current = ""
    for token in tokens:
        candidate = f"{current}{token}".strip()
        if current and text_display_units(candidate) > max_units:
            pieces.append(normalize_text(current))
            current = token
        else:
            current = f"{current}{token}"

    if current.strip():
        pieces.append(normalize_text(current))

    if len(pieces) == 1 and text_display_units(pieces[0]) > max_units:
        hard_pieces = []
        buf = ""
        for char in pieces[0]:
            candidate = f"{buf}{char}"
            if buf and text_display_units(candidate) > max_units:
                hard_pieces.append(normalize_text(buf))
                buf = char
            else:
                buf = candidate
        if buf.strip():
            hard_pieces.append(normalize_text(buf))
        pieces = hard_pieces

    return [piece for piece in pieces if piece]


def flatten_clauses(text, max_units):
    clauses = split_into_clauses(text)
    if not clauses:
        return [normalize_text(text)]

    flattened = []
    for clause in clauses:
        candidates = [clause]
        if text_display_units(clause) > max_units:
            candidates = split_clause_by_connectors(clause)

        for candidate in candidates:
            if text_display_units(candidate) > max_units:
                flattened.extend(split_long_text_by_units(candidate, max_units))
            else:
                flattened.append(candidate)

    return [clause for clause in flattened if clause]


def target_parts_for_block(text, duration, max_units, max_cps, target_duration):
    units = text_display_units(text)
    num_by_duration = max(1, int(duration / target_duration + 0.999))
    num_by_units = max(1, int(units / max_units + 0.999))
    num_by_cps = max(1, int(units / max(max_cps * duration, MIN_TEXT_WEIGHT) + 0.999))
    return max(num_by_duration, num_by_units, num_by_cps)


def merge_chunks_to_target(parts, target_parts, max_units):
    if not parts:
        return [""]
    if len(parts) <= target_parts:
        return parts

    merged = []
    current = ""
    remaining_parts = target_parts
    remaining_items = len(parts)

    for part in parts:
        remaining_items -= 1
        candidate = smart_join(current, part) if current else part
        should_flush = (
            current
            and text_display_units(candidate) > max_units
            and remaining_items >= (remaining_parts - 1)
        )
        if should_flush:
            merged.append(current)
            current = part
            remaining_parts -= 1
        else:
            current = candidate

    if current:
        merged.append(current)
    return merged


def split_text_naturally(text, duration, max_units, max_cps, target_duration):
    normalized = normalize_text(text)
    if not normalized:
        return [""]

    target_parts = target_parts_for_block(normalized, duration, max_units, max_cps, target_duration)
    clauses = flatten_clauses(normalized, max_units)

    if len(clauses) < target_parts:
        expanded = []
        for clause in clauses:
            if text_display_units(clause) > max_units:
                expanded.extend(split_long_text_by_units(clause, max_units))
            else:
                expanded.append(clause)
        clauses = expanded

    parts = merge_chunks_to_target(clauses, target_parts, max_units)
    return [part for part in parts if part.strip()]


def allocate_word_spans(parts, words):
    if not parts or not words:
        return None

    part_weights = [max(1, token_weight(part)) for part in parts]
    total_weight = sum(part_weights)
    total_words = len(words)
    if total_words < len(parts):
        return None

    boundaries = []
    cumulative_weight = 0
    previous_boundary = 0
    for i, weight in enumerate(part_weights[:-1], start=1):
        cumulative_weight += weight
        boundary = round(total_words * cumulative_weight / max(total_weight, 1))
        min_boundary = previous_boundary + 1
        max_boundary = total_words - (len(parts) - i)
        boundary = max(min_boundary, min(boundary, max_boundary))
        boundaries.append(boundary)
        previous_boundary = boundary

    spans = []
    start_idx = 0
    for boundary in boundaries:
        spans.append((start_idx, boundary))
        start_idx = boundary
    spans.append((start_idx, total_words))
    return spans


def allocate_durations_from_words(parts, words, block_start, block_end):
    spans = allocate_word_spans(parts, words)
    if not spans:
        return None

    boundaries = [block_start]
    for i in range(len(spans) - 1):
        curr_start, curr_end = spans[i]
        next_start, _ = spans[i + 1]
        curr_last = words[curr_end - 1]
        next_first = words[next_start]
        left = curr_last.get("end", curr_last.get("start", block_start))
        right = next_first.get("start", next_first.get("end", block_end))
        boundary = (left + right) / 2.0
        boundary = max(boundaries[-1], min(boundary, block_end))
        boundaries.append(boundary)
    boundaries.append(block_end)

    durations = []
    for start, end in zip(boundaries, boundaries[1:]):
        durations.append(max(0.0, end - start))
    if not durations or any(value <= 0 for value in durations):
        return None
    return durations


def allocate_durations(parts, total_duration, min_duration):
    if not parts:
        return []

    weights = [text_display_units(part) for part in parts]
    total_weight = sum(weights) or float(len(parts))
    durations = [max(min_duration, total_duration * weight / total_weight) for weight in weights]
    current_total = sum(durations)

    if current_total > total_duration:
        overflow = current_total - total_duration
        adjustable = [i for i, value in enumerate(durations) if value > min_duration]
        while overflow > 1e-6 and adjustable:
            adjustable_room = sum(durations[i] - min_duration for i in adjustable)
            if adjustable_room <= 1e-6:
                break
            scale = min(1.0, overflow / adjustable_room)
            next_adjustable = []
            for idx in adjustable:
                room = durations[idx] - min_duration
                reduction = room * scale
                durations[idx] -= reduction
                overflow -= reduction
                if durations[idx] - min_duration > 1e-6:
                    next_adjustable.append(idx)
            adjustable = next_adjustable

    if sum(durations) < total_duration:
        durations[-1] += total_duration - sum(durations)

    return durations


def should_split_block(text, duration, max_duration, max_units, max_cps):
    units = text_display_units(text)
    cps = units / max(duration, 0.5)
    return duration > max_duration or units > max_units or cps > max_cps


def audit_and_split_srt(
    input_path,
    output_path,
    max_duration=DEFAULT_MAX_DURATION,
    max_chars_per_line=DEFAULT_MAX_CHARS,
    max_cps=DEFAULT_MAX_CPS,
    min_duration=DEFAULT_MIN_DURATION,
    target_duration=DEFAULT_TARGET_DURATION,
):
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        print("警告: 输入文件为空。")
        return

    blocks = re.split(r"\n\s*\n", content)
    new_blocks = []
    index = 1
    word_timings_by_index = load_word_timing_sidecar(input_path)

    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if len(lines) < 3:
            continue
        try:
            original_index = int(lines[0].strip())
        except ValueError:
            original_index = None

        time_match = TIME_RE.match(lines[1])
        if not time_match:
            continue

        start_str, end_str = time_match.groups()
        start_delta = srt_time_to_delta(start_str)
        end_delta = srt_time_to_delta(end_str)
        duration = max(0.1, (end_delta - start_delta).total_seconds())
        text = normalize_text(" ".join(lines[2:]))

        if not should_split_block(text, duration, max_duration, max_chars_per_line, max_cps):
            new_blocks.append(f"{index}\n{start_str} --> {end_str}\n{text}")
            index += 1
            continue

        sub_texts = split_text_naturally(
            text,
            duration=duration,
            max_units=max_chars_per_line,
            max_cps=max_cps,
            target_duration=target_duration,
        )
        actual_parts = len(sub_texts)
        if actual_parts <= 1:
            new_blocks.append(f"{index}\n{start_str} --> {end_str}\n{text}")
            index += 1
            continue

        word_durations = None
        if original_index is not None and original_index in word_timings_by_index:
            sidecar_segment = word_timings_by_index[original_index]
            sidecar_text = sidecar_segment.get("text", "")
            sidecar_start = sidecar_segment.get("start")
            sidecar_end = sidecar_segment.get("end")
            sidecar_matches = (
                sidecar_text == text
                and sidecar_start is not None
                and sidecar_end is not None
                and abs(float(sidecar_start) - start_delta.total_seconds()) < 0.15
                and abs(float(sidecar_end) - end_delta.total_seconds()) < 0.15
            )
        else:
            sidecar_matches = False

        if sidecar_matches:
            word_durations = allocate_durations_from_words(
                sub_texts,
                sidecar_segment["words"],
                start_delta.total_seconds(),
                end_delta.total_seconds(),
            )

        sub_durations = word_durations or allocate_durations(sub_texts, duration, min_duration)
        cursor = start_delta
        for i, (sub_text, sub_duration) in enumerate(zip(sub_texts, sub_durations)):
            sub_start = cursor
            sub_end = end_delta if i == actual_parts - 1 else cursor + timedelta(seconds=sub_duration)
            new_blocks.append(
                f"{index}\n{delta_to_srt_time(sub_start)} --> {delta_to_srt_time(sub_end)}\n{sub_text}"
            )
            cursor = sub_end
            index += 1

        print(
            f"审计发现超长片段 ({duration:.2f}s, {text_display_units(text):.1f} units)，"
            f"已按语义与 CPS 拆分为 {actual_parts} 段。"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(new_blocks))
    print(f"审计完成，生成优化后的字幕: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python subtitle_splitter.py [InputSrt] [OutputSrt]")
        sys.exit(1)
    audit_and_split_srt(sys.argv[1], sys.argv[2])
