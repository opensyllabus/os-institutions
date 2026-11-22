import csv
from collections import defaultdict
from pathlib import Path

import typer
import yaml
from loguru import logger

from os_institutions.matcher import load_model
from os_institutions.paths import DATA_DIR

app = typer.Typer()


@app.command()
def make_url_mappings(
    domains: Path = typer.Option(
        ...,
        help="Local CSV of domains without an institution, with 'domain' "
        "and 'home_url' columns.",
    ),
    matcher: Path | None = typer.Option(
        None, help='Matcher file (default: the matcher output).'
    ),
    out_dir: Path = typer.Option(
        DATA_DIR, help='Where to write the extended `.yml.new` files.'
    ),
):
    """Turn URLs mapped to null institution into "extra" YAML files.

    This script reads a local CSV (the data is private, so keep it out of
    the repository).  The CSV is expected to have at least two columns:
    'domain' and 'home_url'.  'domain' is a column of domains that failed to
    produce matches in the matcher; 'home_url' is a column of URLs that point
    to the website of the school that corresponding 'domain' should be
    matching against.

    This command runs the matcher against each 'home_url', and if it matches,
    formats the 'domain' as a URL and extends the corresponding entries in the
    `_match_urls.yml' files with those formatted 'domain's.  These extended
    files are saved as `_match_urls.yml.new` inside the institutions module
    data directory (or `--out-dir`).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ids_to_domains = defaultdict(lambda: defaultdict(list))
    unmatched_domains = set()
    model = load_model(matcher)
    with open(domains) as fh:
        reader = csv.DictReader(fh)
        num_matches = 0
        for line in reader:
            if not line['home_url']:
                continue

            res = model.match(
                url=line['home_url'],
                source_url=None,
                email=None,
                school_name=None,
                wikidata_id=None,
                ror_id=None,
                grid_id=None,
            )
            if res:
                identifiers = {'ror_id', 'wikidata_id', 'unitid'}
                found = False
                for _id in identifiers:
                    value = res.get(_id)
                    if value:
                        ids_to_domains[_id][value].append(
                            f'http://{line["domain"]}/'
                        )
                        found = True
                        num_matches += 1
                if not found:
                    raise Exception(
                        'Each match should have at least one'
                        f' identifier: {res}'
                    )
            else:
                unmatched_domains.add(line['domain'])

    logger.info(f'Number of matched domains: {num_matches}')
    logger.info(f'Number of unmatched domains: {len(unmatched_domains)}')

    ids_to_yml = (
        ('ror_id', 'ror_match_urls.yml'),
        ('unitid', 'ipeds_match_urls.yml'),
        ('wikidata_id', 'wikidata_match_urls.yml'),
    )

    for k, file in ids_to_yml:
        in_path = Path(DATA_DIR / file)
        out_path = out_dir / f'{file}.new'
        if in_path.exists():
            extra_urls = yaml.safe_load(in_path.open())
        else:
            extra_urls = {}

        for _id in ids_to_domains[k]:
            if _id in extra_urls:
                for domain in ids_to_domains[k][_id]:
                    if domain not in extra_urls[_id]:
                        extra_urls[_id].append(domain)
            else:
                extra_urls[_id] = ids_to_domains[k][_id]

        yaml.safe_dump(extra_urls, out_path.open('w'))
        logger.info(f'Wrote {out_path}')


if __name__ == '__main__':
    app()
