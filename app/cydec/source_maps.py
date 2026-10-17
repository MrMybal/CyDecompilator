"""Bounded source-map v3 VLQ reader; no sourceRoot or URL is ever fetched."""
import bisect

ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
VALUES = {c: i for i, c in enumerate(ALPHABET)}


def decode(mappings, source_count, name_count):
    if not isinstance(mappings, str) or len(mappings) > 2_000_000:
        raise ValueError('mapping-limit')
    result = {}
    source, original_line, original_column, name_index, count = 0, 0, 0, 0, 0
    for line, encoded in enumerate(mappings.split(';')):
        generated_column = 0
        records = []
        for segment in encoded.split(','):
            if not segment:
                continue
            values, accumulated, shift = [], 0, 0
            for c in segment:
                if c not in VALUES or shift > 30:
                    raise ValueError('invalid-vlq')
                digit = VALUES[c]
                accumulated |= (digit & 31) << shift
                if digit & 32:
                    shift += 5
                else:
                    values.append(-(accumulated >> 1) if accumulated & 1 else accumulated >> 1)
                    accumulated, shift = 0, 0
            if shift or len(values) not in (1, 4, 5):
                raise ValueError('invalid-segment')
            generated_column += values[0]
            if generated_column < 0 or (records and generated_column < records[-1]['column']):
                raise ValueError('invalid-column')
            record = {'column': generated_column}
            if len(values) >= 4:
                source += values[1]
                original_line += values[2]
                original_column += values[3]
                if not 0 <= source < source_count or min(original_line, original_column) < 0:
                    raise ValueError('invalid-source-position')
                record.update(source=source, line=original_line, originalColumn=original_column)
                if len(values) == 5:
                    name_index += values[4]
                    if not 0 <= name_index < name_count:
                        raise ValueError('invalid-name')
                    record['name'] = name_index
            records.append(record)
            count += 1
            if count > 200000:
                raise ValueError('mapping-limit')
        result[line] = records
    return result


def lookup(decoded, line, column):
    records = decoded.get(line - 1, [])
    index = bisect.bisect_right(records, column - 1, key=lambda row: row['column']) - 1
    if index < 0 or 'source' not in records[index]:
        return None
    return records[index]
