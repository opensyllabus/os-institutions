import pandas as pd
from typer.testing import CliRunner

from os_institutions.matcher import Institution, format
from os_institutions.matcher.validate import app, read_input


def institution(_id, name, domain_url):
    data = {field: None for field in Institution.__dataclass_fields__}
    data.update(_id=_id, name=name, url=domain_url)
    return data


def write_matcher(path):
    table = {
        'institutions': [
            institution(0, 'Example University', 'http://example.edu/'),
            institution(1, 'Other College', 'http://other.edu/'),
        ],
        'lookup': {'example.edu': 0, 'other.edu': 1},
    }
    format.save(table, path)


def write_inputs(path):
    # Empty cells are read as NaN, which the matcher must never see.
    path.write_text(
        'url,source_url,email,school_name,count\n'
        'http://example.edu/,,,,5\n'
        ',http://example.edu/syllabi,,,3\n'
        'http://other.edu/,,,,4\n'
        ',,,Unknown School,2\n'
    )


def test_read_input_csv_uses_none_for_missing(tmp_path):
    path = tmp_path / 'in.csv'
    write_inputs(path)

    df = read_input(path)

    assert df.loc[0, 'source_url'] is None
    assert df.loc[1, 'url'] is None
    assert df.loc[0, 'count'] == 5


def test_read_input_parquet(tmp_path):
    path = tmp_path / 'in.parquet'
    pd.DataFrame({'url': ['http://example.edu/'], 'count': [1]}).to_parquet(
        path
    )

    assert read_input(path).loc[0, 'url'] == 'http://example.edu/'


def test_main_writes_validation_csv(tmp_path):
    matcher, inputs, output = (
        tmp_path / 'matcher.json.gz',
        tmp_path / 'in.csv',
        tmp_path / 'out' / 'validation.csv',
    )
    write_matcher(matcher)
    write_inputs(inputs)

    result = CliRunner().invoke(
        app,
        [
            'main',
            '--path',
            str(inputs),
            '--output',
            str(output),
            '--matcher',
            str(matcher),
        ],
    )

    assert result.exit_code == 0, result.output
    df = pd.read_csv(output)
    # The first two rows match one institution and are merged. The unmatched
    # row has no institution, so it is not in the table.
    assert df.set_index('name')['count'].to_dict() == {
        'Example University': 8,
        'Other College': 4,
    }
