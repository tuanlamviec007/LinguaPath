"""Read CSV without silently discarding duplicate headers or surplus cells."""
import csv
import io


def read_strict_csv(text, *, required_columns, optional_columns=()):
    required, allowed = set(required_columns), set(required_columns) | set(optional_columns)
    try:
        reader = csv.reader(io.StringIO(text.lstrip('\ufeff')), strict=True)
        headers = [value.strip() for value in next(reader, [])]
        if not headers or any(not name for name in headers):
            raise ValueError('CSV thiếu tiêu đề cột hoặc có tên cột trống.')
        if len(headers) != len(set(headers)):
            raise ValueError('CSV có tiêu đề cột trùng nhau.')
        if required - set(headers):
            raise ValueError('CSV thiếu cột bắt buộc: ' + ', '.join(sorted(required - set(headers))))
        if set(headers) - allowed:
            raise ValueError('CSV có cột không được hỗ trợ: ' + ', '.join(sorted(set(headers) - allowed)))
        rows = []
        for values in reader:
            if not values:
                continue
            if len(values) != len(headers):
                raise ValueError(f'Dòng {reader.line_num}: số ô không khớp số cột CSV.')
            row = {key: value.strip() for key, value in zip(headers, values)}
            if any(row.values()):
                rows.append(row)
        return rows
    except csv.Error as exc:
        raise ValueError(f'CSV không hợp lệ: {exc}') from exc
