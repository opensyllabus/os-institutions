import pandas as pd
import pytest

from os_institutions.matcher import build
from os_institutions.matcher.matcher import InstitutionMatcher
from os_institutions.matcher.url_keys import (
    build_url_key_table,
    path_prefix_keys,
    path_segments,
)

DAL = 'Dalhousie University'


def make(*insts):
    """insts: (name, [urls]) -> InstitutionMatcher built through build_table"""
    df = pd.DataFrame(
        {
            'name': [n for n, _ in insts],
            'names': [[n] for n, _ in insts],
            'urls': [list(u) for _, u in insts],
        }
    )
    table = build.build_table(df)
    return InstitutionMatcher(table), table['lookup']


@pytest.fixture(scope='module')
def dal():
    return make(
        (
            'Canadian Institute of Fisheries Technology',
            ['https://www.dal.ca/faculty/engineering/cift.html'],
        ),
        (DAL, ['https://www.dal.ca/']),
        (
            'Dalhousie Faculty of Law',
            ['https://www.dal.ca/faculty/law.html'],
        ),
        ('Dalhousie Medical School', ['https://www.dal.ca/dept/medicine/']),
    )


def name(matcher, **kw):
    inst = matcher(**kw)
    return inst.name if inst else None


@pytest.mark.parametrize(
    'url',
    [
        'https://www.dal.ca/faculty/arts/english.html',
        'https://www.dal.ca/faculty/engineering/undergraduate.html',
        'https://www.dal.ca/dept/computer-science.html',
        'https://www.dal.ca/study/programs/undergraduate.html',
        'https://www.dal.ca/sites/registrar/calendar.html',
        'https://www.dal.ca/diff/x',
        'https://www.dal.ca/',
    ],
)
def test_dalhousie_links_not_hijacked(dal, url):
    assert name(dal[0], url=url) == DAL


def test_dalhousie_units_resolve_to_units(dal):
    m = dal[0]
    cift = 'Canadian Institute of Fisheries Technology'
    assert (
        name(m, url='https://www.dal.ca/faculty/engineering/cift.html') == cift
    )
    assert (
        name(m, url='https://www.dal.ca/faculty/engineering/cift/people.html')
        == cift
    )
    assert name(m, url='https://www.dal.ca/faculty/arts/x') == DAL
    assert (
        name(m, url='https://www.dal.ca/faculty/law.html')
        == 'Dalhousie Faculty of Law'
    )
    assert (
        name(m, url='https://www.dal.ca/dept/medicine/about')
        == 'Dalhousie Medical School'
    )


def test_only_full_paths_registered(dal):
    lookup = dal[1]
    for key in (
        'dal.ca/faculty',
        'dal.ca/faculty/engineering',
        'dal.ca/study',
    ):
        assert key not in lookup
    assert 'dal.ca/faculty/engineering/cift' in lookup  # extension stripped
    assert 'dal.ca/faculty/law' in lookup
    assert 'dal.ca/dept/medicine' in lookup


def test_bare_domain_owner_is_institution_with_bare_url():
    # three unit URLs listed before the university itself
    _, lookup = make(
        ('A Unit', ['https://www.x.edu/a/b']),
        ('B Unit', ['https://www.x.edu/c/d']),
        ('X University', ['https://www.x.edu']),
    )
    assert lookup['x.edu'] == 2


def test_bare_domain_falls_back_to_mode():
    _, lookup = make(
        ('A', ['https://www.x.edu/a/b']),
        ('B', ['https://www.x.edu/c/d']),
        ('B2', ['https://www.x.edu/c/e']),
    )
    assert lookup['x.edu'] in (0, 1, 2)


def test_multi_campus_single_segment_keys_kept():
    m, lookup = make(
        (
            'Paul Mitchell Overland Park',
            ['https://paulmitchell.edu/overlandpark'],
        ),
        ('Paul Mitchell Reno', ['https://www.paulmitchell.edu/reno']),
        ('Paul Mitchell the School', ['https://paulmitchell.edu']),
        ('Anschutz', ['https://www.ucdenver.edu/anschutz']),
        ('CU Denver', ['https://www.ucdenver.edu']),
        ('Canyons', ['https://curricunet.com/canyons']),
        ('Mission', ['https://curricunet.com/mission']),
        ('UTAS Nizwa', ['https://www.utas.edu.om/nizwa']),
        ('UTAS Sur', ['https://www.utas.edu.om/sur']),
        ('Anahuac Queretaro', ['https://www.anahuac.mx/queretaro']),
        ('Anahuac Mexico', ['https://www.anahuac.mx']),
        ('BatStateU Lobo', ['https://batstateu.edu.ph/lobo']),
        ('BatStateU', ['https://batstateu.edu.ph']),
        ('PUP San Pedro', ['https://www.pup.edu.ph/sanpedro']),
    )
    assert (
        name(m, url='https://www.paulmitchell.edu/reno/programs')
        == 'Paul Mitchell Reno'
    )
    assert (
        name(m, url='https://paulmitchell.edu/overlandpark/x/y.html')
        == 'Paul Mitchell Overland Park'
    )
    assert (
        name(m, url='https://paulmitchell.edu/other')
        == 'Paul Mitchell the School'
    )
    assert (
        name(m, url='https://www.ucdenver.edu/anschutz/academics')
        == 'Anschutz'
    )
    assert name(m, url='https://www.ucdenver.edu/academics') == 'CU Denver'
    assert name(m, url='https://curricunet.com/canyons/Course/1') == 'Canyons'
    assert name(m, url='https://curricunet.com/mission/Course/1') == 'Mission'
    assert (
        name(m, url='https://www.utas.edu.om/nizwa/en/programs')
        == 'UTAS Nizwa'
    )
    assert (
        name(m, url='https://www.anahuac.mx/queretaro/oferta')
        == 'Anahuac Queretaro'
    )
    assert name(m, url='https://batstateu.edu.ph/lobo/x') == 'BatStateU Lobo'
    assert name(m, url='https://batstateu.edu.ph/campuses/x') == 'BatStateU'
    assert (
        name(m, url='https://www.pup.edu.ph/sanpedro/courses')
        == 'PUP San Pedro'
    )


def test_deep_url_does_not_register_first_segment():
    m, lookup = make(
        ('University of Alberta', ['https://www.ualberta.ca']),
        ('Steadward Centre', ['https://www.ualberta.ca/en/steadward-centre']),
    )
    assert 'ualberta.ca/en' not in lookup
    assert 'ualberta.ca/en/steadward-centre' in lookup
    assert (
        name(m, url='https://www.ualberta.ca/en/arts/programs')
        == 'University of Alberta'
    )
    assert (
        name(m, url='https://www.ualberta.ca/en/steadward-centre/about')
        == 'Steadward Centre'
    )


def test_single_segment_shared_by_two_goes_to_mode():
    _, lookup = make(
        ('One', ['https://x.edu/school']),
        ('Two', ['https://x.edu/school', 'https://x.edu/school/']),
        ('Owner', ['https://x.edu']),
    )
    assert lookup['x.edu/school'] == 1


def test_macdonald_campus_under_mcgill():
    m, _ = make(
        ('McGill University', ['https://www.mcgill.ca/']),
        (
            'Collège MacDonald',
            [
                'http://www.mcgill.ca/macdonald/',
                'https://www.mcgill.ca/macdonald/macdonald-campus',
            ],
        ),
        ('Air and Space Law', ['https://www.mcgill.ca/iasl/']),
    )
    assert (
        name(m, url='https://www.mcgill.ca/macdonald/students')
        == 'Collège MacDonald'
    )
    assert name(m, url='https://www.mcgill.ca/study/x') == 'McGill University'


def test_campus_deep_path_and_landing_page():
    m, _ = make(
        ('Purdue West Lafayette', ['https://www.purdue.edu/']),
        (
            'Purdue Indianapolis',
            ['https://www.purdue.edu/campuses/indianapolis'],
        ),
        ('Johnson University', ['http://www.johnsonu.edu/Home.aspx']),
        (
            'Johnson University Florida',
            ['https://www.johnsonu.edu/Florida/Home.aspx'],
        ),
        ('CvSU', ['https://cvsu.edu.ph']),
        ('CvSU Silang', ['https://cvsu.edu.ph/silang-campus/']),
    )
    assert (
        name(m, url='https://www.purdue.edu/campuses/indianapolis/x/y')
        == 'Purdue Indianapolis'
    )
    assert (
        name(m, url='https://www.purdue.edu/campuses/other')
        == 'Purdue West Lafayette'
    )
    assert (
        name(m, url='https://www.johnsonu.edu/florida/academics')
        == 'Johnson University Florida'
    )
    assert name(m, url='https://www.johnsonu.edu/x') == 'Johnson University'
    assert (
        name(m, url='https://cvsu.edu.ph/silang-campus/admissions')
        == 'CvSU Silang'
    )


def test_deep_path_under_excluded_prefix_is_kept():
    # `/content` alone says nothing, but `/content/71` is a campus of its own
    # (CPSU); only the bare excluded prefix is dropped.
    m, table = make(
        ('CPSU', ['https://www.cpsu.edu.ph/']),
        ('CPSU Hinoba-an', ['https://www.cpsu.edu.ph/content/71']),
        ('CPSU Other', ['https://www.cpsu.edu.ph/content']),
    )
    assert 'cpsu.edu.ph/content/71' in table
    assert 'cpsu.edu.ph/content' not in table
    assert (
        name(m, url='https://www.cpsu.edu.ph/content/71/news')
        == 'CPSU Hinoba-an'
    )
    assert name(m, url='https://www.cpsu.edu.ph/content/9') == 'CPSU'


def test_path_segments_normalization():
    assert path_segments('https://x.edu/A/B/index.html') == ['a', 'b']
    assert path_segments('https://x.edu/a/b.PHP') == ['a', 'b']
    assert path_segments('https://x.edu/a/default.aspx') == ['a']
    assert path_segments('https://x.edu/a/Home.aspx') == ['a']
    assert path_segments('https://x.edu/home') == ['home']
    assert path_segments('https://x.edu/') == []
    assert path_segments(None) == []


def test_path_prefix_keys_longest_first():
    assert path_prefix_keys('https://www.dal.ca/a/b/c.html') == [
        'dal.ca/a/b/c',
        'dal.ca/a/b',
        'dal.ca/a',
    ]
    assert path_prefix_keys('https://www.dal.ca/') == ['dal.ca']
    assert path_prefix_keys(None) == []


def test_table_function_directly():
    table = build_url_key_table(
        [(0, ['https://u.edu/a/b']), (1, ['https://u.edu'])]
    )
    assert table['u.edu'] == 1
    assert table['u.edu/a/b'] == 0
    assert 'u.edu/a' not in table
