"""Read taxon identifiers from common IQ-TREE alignment formats for outgroup selection.

Only identifiers, not sequences, are loaded into memory. Files remain untouched.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path


def _unique(names: list[str]) -> list[str]:
    return list(dict.fromkeys(n for n in names if n))


def read_alignment_taxa(path: str | Path) -> list[str]:
    """Read FASTA, PHYLIP, or NEXUS taxon labels; raise on unrecognized files.

    The GUI deliberately avoids guessing names in ambiguous PHYLIP formats.
    FASTA identifiers follow the common convention: first token after '>'.
    """
    path = Path(path)
    with path.open('r', encoding='utf-8-sig', errors='replace') as f:
        first = ''
        for line in f:
            if line.strip():
                first = line.strip()
                break
        if not first:
            raise ValueError('Alignment 파일이 비어 있습니다.')
        if first.startswith('>'):
            names = []
            while True:
                if first.startswith('>'):
                    ident = first[1:].strip().split(maxsplit=1)
                    if not ident:
                        raise ValueError('이름이 없는 FASTA 헤더가 있습니다.')
                    names.append(ident[0])
                for line in f:
                    if line.lstrip().startswith('>'):
                        first = line.lstrip().strip()
                        break
                else:
                    break
            return _validate(names)

        if re.match(r'^\s*#NEXUS\b', first, re.I):
            names = []
            in_matrix = False
            # NEXUS often contains comments. Ignore bracket-delimited comments, even multiline.
            comment_level = 0
            for line in f:
                clean = []
                i = 0
                while i < len(line):
                    ch = line[i]
                    if ch == '[':
                        comment_level += 1
                    elif ch == ']' and comment_level:
                        comment_level -= 1
                    elif not comment_level:
                        clean.append(ch)
                    i += 1
                line = ''.join(clean).strip()
                if not line:
                    continue
                if not in_matrix:
                    m = re.search(r'\bmatrix\b', line, re.I)
                    if not m:
                        continue
                    in_matrix = True
                    line = line[m.end():].strip()
                    if not line:
                        continue
                if line.startswith(';'):
                    break
                # shlex handles 'taxon with spaces' and single-token IDs.
                try:
                    tokens = shlex.split(line.rstrip(';'), posix=True)
                except ValueError as ex:
                    raise ValueError(f'NEXUS MATRIX 레이블을 읽을 수 없습니다: {ex}') from ex
                if len(tokens) >= 2:
                    # Interleaved NEXUS may repeat labels; deduplicate in order.
                    names.append(tokens[0])
                if line.endswith(';'):
                    break
            return _validate(names)

        m = re.match(r'^(\d+)\s+(\d+)(?:\s|$)', first)
        if m:
            expected = int(m.group(1))
            names = []
            for line in f:
                if len(names) >= expected:
                    break
                line = line.strip()
                if not line:
                    continue
                # Relaxed PHYLIP: first whitespace-delimited token is the taxon name.
                # Sequential/interleaved continuation lines are not taxa.
                fields = line.split(maxsplit=1)
                if len(fields) < 2:
                    continue
                label, sequence = fields
                if not re.match(r'^[A-Za-z?*\-\.0-9\s]+$', sequence):
                    continue
                names.append(label)
            if len(names) != expected:
                raise ValueError(f'PHYLIP에서 {expected}개 이름을 예상했지만 {len(names)}개를 읽었습니다. 비표준 포맷이면 FASTA로 변환하십시오.')
            return _validate(names)
    raise ValueError('Outgroup 자동 선택은 FASTA, PHYLIP, NEXUS에서 지원됩니다.')


def _validate(names: list[str]) -> list[str]:
    values = _unique(names)
    if not values:
        raise ValueError('Alignment에서 분류군 이름을 찾을 수 없습니다.')
    if any(',' in s for s in values):
        raise ValueError('분류군 이름에 쉼표가 있어 IQ-TREE -o 옵션으로 안전하게 결합할 수 없습니다.')
    return values


def join_outgroups(names: list[str]) -> str:
    """Comma-separated -o format expected by IQ-TREE 2."""
    if any(',' in x for x in names):
        raise ValueError('분류군 이름에 쉼표를 사용할 수 없습니다.')
    return ','.join(_unique(names))
