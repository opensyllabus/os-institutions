from os_institutions.matcher.matcher import Institution


def test_institution_from_dict():
    data = dict(
        _id=1,
        grid_id='grid_id',
        ror_id="ror_id",
        wikidata_id='wikidata_id',
        unitid=0,
        city='city',
        name='name',
        lat=0.0,
        lng=0.0,
        url='http://example.com',
        country_code='code',
        country='country',
        state_code='code',
        state='state',
        enrollment=0,
        two_year=False,
        four_year=True,
        graduate=True,
        research=True,
        wikipedia_url='https://en.wikipedia.org',
        description='description',
        image_url='http://example.com',
    )

    res = Institution.from_dict(data)

    for key, val in data.items():
        assert getattr(res, key) == val
