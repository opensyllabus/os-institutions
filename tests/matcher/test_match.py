import os

import pytest

from os_institutions.matcher import artifact, load_model


@pytest.fixture(scope='module')
def matcher():
    # The matcher is a private W&B artifact. Skip when it is neither cached
    # locally nor downloadable (TODO(W&B removal in PR #2)).
    if (
        not os.environ.get('WANDB_API_KEY')
        and not artifact.local_path.exists()
    ):
        pytest.skip('matcher artifact needs WANDB_API_KEY (or a local cache)')
    return load_model()


@pytest.mark.parametrize(
    'match_kwargs,wikidata_id',
    [
        (dict(url='http://web.stanford.edu/class/cs224n/'), 'Q41506'),
        (dict(url='https://www.mit.edu/~9.520/fall19/'), 'Q49108'),
        (
            dict(
                url='https://web.archive.org/web/20030814022411/http:/www.pas.rochester.edu/~rajeev/PHY408/index.html'
            ),
            'Q149990',
        ),
        (
            dict(url='https://sites.google.com/a/g.clemson.edu/cpsc-8810/'),
            'Q631066',
        ),
        (dict(source_url='http://web.stanford.edu/syllabi/'), 'Q41506'),
        (dict(source_url='https://www.mit.edu/syllabi/'), 'Q49108'),
        (
            dict(
                source_url='https://web.archive.org/web/20030814022411/http:/www.pas.rochester.edu/syllabi/'
            ),
            'Q149990',
        ),
        (
            dict(
                source_url='https://sites.google.com/a/g.clemson.edu/syllabi/'
            ),
            'Q631066',
        ),
        (dict(email='david@stanford.edu'), 'Q41506'),
        (dict(email='david@mit.edu'), 'Q49108'),
        # example rows:
        # ror_id,grid_id,wikidata_id,unitid,name
        # 00f54p054,grid.168010.e,Q41506,243744,Stanford University
        # 042nb2s44,grid.116068.8,Q49108,166683,Massachusetts Institute of Technology
        # 01y2jtd41,grid.14003.36,Q838330,240444,University of Wisconsin–Madison
        # 04ckqgs57,grid.258533.a,Q1797768,203535,Kenyon College
        # 03vek6s52,grid.38142.3c,Q13371,166027,Harvard University
        (dict(school_name='Stanford University'), 'Q41506'),
        (dict(school_name='STANFORD UNIVERSITY'), 'Q41506'),
        (dict(school_name='Stanford'), 'Q41506'),
        (dict(school_name='stanford'), 'Q41506'),
        (dict(school_name='Kenyon College'), 'Q1797768'),
        (dict(school_name='University of Wisconsin-Madison'), 'Q838330'),
        (dict(school_name='University of Wisconsin Madison'), 'Q838330'),
        (dict(school_name='University of Wisconsin, Madison'), 'Q838330'),
        (dict(school_name='UW Madison'), 'Q838330'),
        # Direct institution ID lookups
        (dict(wikidata_id='Q41506'), 'Q41506'),  # Stanford
        (dict(ror_id='03vek6s52'), 'Q13371'),  # Harvard
        (dict(grid_id='grid.38142.3c'), 'Q13371'),  # Harvard
        # IPEDS unitid lookups
        (dict(unitid=243744), 'Q41506'),  # Stanford
        (dict(unitid=166027), 'Q13371'),  # Harvard
        (dict(unitid=203535), 'Q1797768'),  # Kenyon College
        # Multiple IDs where one exists
        (
            dict(wikidata_id=None, ror_id='03vek6s52', grid_id=None),
            'Q13371',
        ),  # Harvard
        (
            dict(wikidata_id=None, ror_id=None, grid_id='grid.168010.e'),
            'Q41506',
        ),  # Stanford
        (
            dict(wikidata_id=None, ror_id=None, grid_id=None, unitid=243744),
            'Q41506',
        ),  # Stanford
        # TODO: Scrub "college" + "university"?
        pytest.param(
            dict(school_name='Kenyon'), 'Q1797768', marks=pytest.mark.xfail
        ),
        pytest.param(
            dict(school_name='Yale'), 'Q49108', marks=pytest.mark.xfail
        ),  # Fixed: Yale's wikidata_id was incorrectly set to Kenyon's
    ],
)
def test_match(matcher, match_kwargs, wikidata_id):
    res = matcher(**match_kwargs)
    assert res.wikidata_id == wikidata_id
