import csv
from collections import defaultdict
from pathlib import Path

import wandb
import yaml
from loguru import logger
from typer import Typer

from os_institutions.matcher import load_model
from os_institutions.paths import DATA_DIR
from os_institutions.utils import first_file, wandb_artifact, wandb_init

app = Typer()


ARTIFACT = 'opensyllabus/institutions/domains-without-institution.csv:v0'


@app.command()
def make_url_mappings():
    """Turn URLs mapped to null institution into "extra" YAML files.

    This script reads a CSV uploaded to W&B via the
    `upload_institution_mapping` command.  The CSV is expected to have at least
    two columns: 'domain' and 'home_url'.  'domain' is a column of domains that
    failed to produce matches in the matcher; 'home_url' is a column of URLs
    that point to the website of the school that corresponding 'domain' should
    be matching against.

    This command runs the matcher against each 'home_url', and if it matches,
    formats the 'domain' as a URL and extends the corresponding entries in the
    `_match_urls.yml' files with those formatted 'domain's.  These extended
    files are saved as `_match_urls.yml.new` inside the institutions module
    data directory.
    """
    wandb_init(group='institutions')

    ids_to_domains = defaultdict(lambda: defaultdict(list))
    unmatched_domains = set()
    model = load_model()
    artifact = first_file(wandb_artifact(ARTIFACT))
    with open(artifact) as fh:
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
        out_path = Path(DATA_DIR / f'{file}.new')
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


@app.command()
def upload_institution_mapping(path: Path):
    wandb_init(group='institutions')

    # XXX: Good way to annotate with the dataset version that the domain sheet
    # was based on?
    artifact = wandb.Artifact(
        'domains-without-institution.csv', type='dataset'
    )
    logger.info(f'Uploading {path.name}')
    artifact.add_file(path, name='domains-without-institution.csv')
    wandb.log_artifact(artifact)


if __name__ == '__main__':
    app()
