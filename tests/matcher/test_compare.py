import json
import pickle

import pandas as pd
from typer.testing import CliRunner

from os_institutions.matcher import Institution
from os_institutions.matcher.compare import app


def institution(_id, name, ror_id, domain_url):
    data = {field: None for field in Institution.__dataclass_fields__}
    data.update(_id=_id, name=name, ror_id=ror_id, url=domain_url)
    return data


def write_matcher(path, institutions, lookup):
    with open(path, 'wb') as fh:
        pickle.dump({'institutions': institutions, 'lookup': lookup}, fh)


EXAMPLE = ('Example University', 'ror:example', 'http://example.edu/')
OTHER = ('Other College', 'ror:other', 'http://other.edu/')
THIRD = ('Third Institute', 'ror:third', 'http://third.edu/')

SECRET_ROWS = (
    'url,source_url,email,school_name,count\n'
    'http://example.edu/,,,,5\n'
    ',http://example.edu/syllabi,,,3\n'
    'http://other.edu/,,,,4\n'
    ',,,Unknown School,2\n'
)


def make_inputs(tmp_path):
    sample = tmp_path / 'in.csv'
    sample.write_text(SECRET_ROWS)

    # In the old matcher other.edu is institution 1; in the new one the row
    # indexes differ and example.edu is gone, other.edu moves to a different
    # institution, and third.edu is new (but unused by the sample).
    old = tmp_path / 'old.pickle'
    write_matcher(
        old,
        [institution(0, *EXAMPLE), institution(1, *OTHER)],
        {'example.edu': 0, 'other.edu': 1},
    )
    new = tmp_path / 'new.pickle'
    write_matcher(
        new,
        [institution(0, *OTHER), institution(1, *THIRD)],
        {'other.edu': 0, 'third.edu': 1},
    )
    return sample, old, new


def run(tmp_path, *args):
    out = tmp_path / 'out'
    result = CliRunner().invoke(
        app, [*args, '--output-dir', str(out)], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    return out


def test_compare_reports_changes(tmp_path):
    sample, old, new = make_inputs(tmp_path)

    out = run(
        tmp_path,
        '--path', str(sample),
        '--old', str(old),
        '--new', str(new),
    )  # fmt: skip

    summary = json.loads((out / 'summary.json').read_text())
    assert summary['sample'] == {'rows': 4, 'count': 14}
    assert summary['old']['matched_count'] == 12
    assert summary['new']['matched_count'] == 4
    # example.edu rows (5 + 3) stop matching; other.edu keeps its institution
    # even though its row index changed.
    assert summary['changed'] == {
        'rows': 2,
        'count': 8,
        'newly_matched_count': 0,
        'no_longer_matched_count': 8,
        'reassigned_count': 0,
    }
    assert summary['lost_institutions'] == 1
    assert summary['gained_institutions'] == 0
    assert summary['top_lost'] == [
        {'institution': 'Example University', 'count': 8}
    ]
    df = pd.read_csv(out / 'validation.csv')
    assert df.set_index('name')['count'].to_dict() == {'Other College': 4}


def test_compare_without_baseline(tmp_path):
    sample, _, new = make_inputs(tmp_path)

    out = run(tmp_path, '--path', str(sample), '--new', str(new))

    summary = json.loads((out / 'summary.json').read_text())
    assert summary['old'] is None
    assert summary['new']['matched_count'] == 4
    assert 'No baseline release yet' in (out / 'summary.md').read_text()


def test_compare_identical_matchers_change_nothing(tmp_path):
    sample, old, _ = make_inputs(tmp_path)

    out = run(
        tmp_path,
        '--path', str(sample),
        '--old', str(old),
        '--new', str(old),
    )  # fmt: skip

    summary = json.loads((out / 'summary.json').read_text())
    assert summary['changed']['rows'] == 0
    assert summary['top_changed'] == []


def test_compare_writes_no_sample_values(tmp_path):
    sample, old, new = make_inputs(tmp_path)

    out = run(
        tmp_path,
        '--path', str(sample),
        '--old', str(old),
        '--new', str(new),
    )  # fmt: skip

    written = ''.join(p.read_text() for p in out.iterdir())
    # Sample inputs never appear; only matched institutions (public data) do.
    assert 'Unknown School' not in written
    assert 'example.edu/syllabi' not in written
