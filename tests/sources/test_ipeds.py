import pandas as pd
import pytest

from os_institutions.sources.ipeds import parse_alias


@pytest.mark.parametrize(
    'string,alias',
    [
        ('Bentley', ['Bentley']),
        ('steven papageorge hair academy', ['steven papageorge hair academy']),
        ('UT Permian Basin', ['UT Permian Basin']),
        ('Ogle School', ['Ogle School']),
        (
            'Ameritech College of Healthcare',
            ['Ameritech College of Healthcare'],
        ),
        (
            'Hussian College - Daymar College Columbus',
            ['Hussian College - Daymar College Columbus'],
        ),
        ('PSC', ['PSC']),
        ('UC Davis', ['UC Davis']),
        (
            "Mount St. Mary's Seminary & School of Theology",
            ["Mount St. Mary's Seminary & School of Theology"],
        ),
        ('Cal State East Bay', ['Cal State East Bay']),
        ('KD Conservatory', ['KD Conservatory']),
        ('BCC', ['BCC']),
        ('IDSVA', ['IDSVA']),
        (
            'Pinellas Technical Education Center-Clearwater',
            ['Pinellas Technical Education Center-Clearwater'],
        ),
        ('LCCC', ['LCCC']),
        ('McNeese', ['McNeese']),
        ('BSU|Bridgewater State', ['BSU', 'Bridgewater State']),
        ('Memorial Medical Center', ['Memorial Medical Center']),
        (
            'SMCC  SWCC  Southwest Community College  Southwest  South West Mississippi Community College  South West Community College',  # noqa
            [
                'SMCC',
                'SWCC',
                'Southwest Community College',
                'Southwest',
                'South West Mississippi Community College',
                'South West Community College',
            ],
        ),
        (
            'Northwest Nazarene University/Northwest Nazarene College/NNU/NNC/Northwest Nazarene University',  # noqa
            [
                'Northwest Nazarene University',
                'Northwest Nazarene College',
                'NNU',
                'NNC',
                'Northwest Nazarene University',
            ],
        ),
        (
            'Enterprise-Ozark Community College   Enterprise State Junior College',  # noqa
            [
                'Enterprise-Ozark Community College',
                'Enterprise State Junior College',
            ],
        ),
        (pd.NA, []),
        (None, []),
        ('', []),
    ],
)
def test_parse_alias(string, alias):
    assert parse_alias(string) == alias
