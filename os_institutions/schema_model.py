import datetime
from urllib.parse import urlparse

import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Object, Series

from os_institutions.paths import DATA_DIR
from os_institutions.utils import read_yaml


def unitid_above_minimum(col):
    return col >= 100_000


def grid_id_startswith_grid(col):
    return col.str.startswith("grid")


def wikidata_id_startswith_Q(col):
    return col.str.startswith("Q")


def wikipedia_url_contains_wikipedia(col):
    return col.apply(
        lambda d: (
            urlparse(d).netloc.endswith("wikipedia.org")
            if d is not pd.NA
            else pd.NA
        )
    )


def longitude_within_range(col):
    return (col >= -180.0) & (col <= 180.0)


def latitude_within_range(col):
    return (col >= -90.0) & (col <= 90.0)


def str_startswith_http(col):
    return col.str.startswith("http")


def year_within_range(col):
    return (col >= 900) & (col <= datetime.datetime.now().year + 1)


def unsigned_int(col):
    return col >= 0


def list_without_none(col):
    return col.dropna().apply(lambda xs: None not in xs)


class Dataset(pa.DataFrameModel):
    @pa.check("grid_id")
    def check_grid_id(cls, col):
        return grid_id_startswith_grid(col)

    @pa.check("wikidata_id")
    def check_wikidata_id(cls, col):
        return wikidata_id_startswith_Q(col)

    @pa.check("unitid")
    def check_unitid(cls, col):
        return unitid_above_minimum(col)

    @pa.check("lat")
    def check_lat(cls, col):
        return latitude_within_range(col)

    @pa.check("lng")
    def check_lng(cls, col):
        return longitude_within_range(col)

    @pa.check("url")
    def check_url(cls, col):
        return str_startswith_http(col)

    @pa.check("wikipedia_url")
    def check_wikipedia_url(cls, col):
        return (
            str_startswith_http(col).all()
            and wikipedia_url_contains_wikipedia(col).all()
        )

    @pa.check("image_url")
    def check_image_url(cls, col):
        return str_startswith_http(col)

    @pa.check("names")
    def check_names(cls, col):
        return list_without_none(col)

    @pa.check("urls")
    def check_urls(cls, col):
        return list_without_none(col)

    @pa.dataframe_check()
    def at_least_one_id(cls, df):
        return (
            df.ror_id.notna() | df.unitid.notna() | df.wikidata_id.notna()
        ).all()

    @pa.dataframe_check()
    def ror_id_count(cls, df):
        ror_id_count = df.ror_id.count()
        return (
            ror_id_count >= df.wikidata_id.count()
            and ror_id_count >= df.unitid.count()
            and ror_id_count >= df.grid_id.count()
        )

    @pa.dataframe_check()
    def unique_ror_id(cls, df):
        return (df.ror_id.value_counts() == 1).all()

    @pa.dataframe_check()
    def unique_grid_id(cls, df):
        return (df.grid_id.value_counts() == 1).all()

    @pa.dataframe_check()
    def unique_wikidata_id(cls, df):
        return (df.wikidata_id.value_counts() == 1).all()

    @pa.dataframe_check()
    def unique_unitid(cls, df):
        return (df.unitid.value_counts() == 1).all()

    @pa.dataframe_check()
    def state_count(cls, df):
        # Filter for US institutions only
        usa = df[df["country_code"] == "US"]

        # If there are no US institutions, then something went wrong
        if usa.empty:
            return False

        # For US, ensure every record with a state code has a state name.
        state_code_count = usa.state_code.notna().sum()
        state_name_count = usa.state.notna().sum()

        return state_code_count == state_name_count

    @pa.dataframe_check()
    def required_fields(cls, df):
        # Every institution should have a country code,
        # a country name and an institution name.
        country_code_count = sum(df.country_code.notna())
        country_count = sum(df.country.notna())
        name_count = sum(df.name.notna())

        return len(df) == country_code_count == country_count == name_count

    @pa.dataframe_check()
    def institution_category_invariants(cls, df):
        research = df[df.research]
        graduate = df[df.graduate]
        four_year = df[df.four_year]
        two_year = df[df.two_year]

        # Research and graduate institutions are both subsets of four year
        # institutions. Two year institutions should be distinct.
        return (
            research.index.isin(graduate.index).all()
            and graduate.index.isin(four_year.index).all()
            and not two_year.index.isin(four_year.index).any()
        )

    @pa.dataframe_check()
    def check_ipeds_cases(cls, df):
        # TODO: Simplify test target fields to reduce maintenance overhead
        # TODO: Remove asserts and convert it into pandera supported format
        ipeds_cases = read_yaml(DATA_DIR / "ipeds_cases.yml", pandas=False)

        for ipeds_unitid, case in ipeds_cases.items():
            row = df[df.unitid == ipeds_unitid].iloc[0]
            assert row is not None

            res = row.replace({pd.NA: None}).to_dict()

            for key, val in case.items():
                if key in res:
                    assert res[key] == val, (
                        f"[{ipeds_unitid=}] {key=}: {res[key]=} equals {val=}"
                    )

        return True

    @pa.dataframe_check()
    def additional_cases(cls, df):
        # TODO: Simplify test target fields to reduce maintenance overhead
        # TODO: Remove asserts and convert it into pandera supported format
        ror_cases = read_yaml(DATA_DIR / "ror_cases.yml", pandas=False)

        for ror_id, case in ror_cases.items():
            row = df[df.ror_id == ror_id].iloc[0]
            assert row is not None

            res = row.replace({pd.NA: None}).to_dict()

            for key, val in case.items():
                if key in res:
                    # Wikidata mirrors round coordinates to 6 decimals.
                    if isinstance(val, float) and res[key] is not None:
                        same = abs(res[key] - val) < 1e-6
                    else:
                        same = res[key] == val
                    assert same, (
                        f"[{ror_id=}] {key=}: {res[key]=} equals {val=}"
                    )

        return True


class IPEDS(pa.DataFrameModel):
    @pa.check("ipeds_unitid")
    def check_ipeds_unitid(cls, col):
        return unitid_above_minimum(col)

    @pa.check("ipeds_ialias")
    def check_ipeds_ialias(cls, col):
        return list_without_none(col)

    @pa.check("ipeds_webaddr")
    def check_ipeds_webaddr(cls, col):
        return str_startswith_http(col)

    @pa.check("ipeds_control")
    def check_ipeds_control(cls, col):
        return (col >= 1) & (col <= 3)

    @pa.check("ipeds_c21basic")
    def check_ipeds_c21basic(cls, col):
        return (col >= 1) & (col <= 33)

    @pa.check("ipeds_longitud")
    def check_ipeds_longitud(cls, col):
        return longitude_within_range(col)

    @pa.check("ipeds_latitude")
    def check_ipeds_latitude(cls, col):
        return latitude_within_range(col)

    @pa.check("ipeds_effylev")
    def check_ipeds_effylev(cls, col):
        return col == 1

    @pa.check("ipeds_efytotlt")
    def check_ipeds_efytotlt(cls, col):
        return col >= 1

    @pa.dataframe_check
    def duplicated(cls, df):
        return not df[["ipeds_unitid", "ipeds_instnm"]].duplicated().any()

    @pa.dataframe_check
    def unitid_not_na(cls, df):
        return df.ipeds_unitid.notna().all()


class RORDist(pa.DataFrameModel):
    @pa.check("id")
    def check_id(cls, col):
        return col.str.startswith("https://ror.org/")


class ROR(pa.DataFrameModel):
    @pa.check("ror_wikipedia_url")
    def check_ror_wikipedia_url(cls, col):
        return (
            str_startswith_http(col).all()
            and wikipedia_url_contains_wikipedia(col).all()
        )

    @pa.check("ror_established")
    def check_ror_established(cls, col):
        return year_within_range(col)

    @pa.check("ror_state_code")
    def check_ror_state_code(cls, col):
        # Make sure state code doesn't contain numbers
        return ~col.str.contains(r"\d", na=False)

    @pa.check("ror_lat")
    def check_ror_lat(cls, col):
        return latitude_within_range(col)

    @pa.check("ror_lng")
    def check_ror_lng(cls, col):
        return longitude_within_range(col)

    @pa.check("ror_grid_id")
    def check_ror_grid_id(cls, col):
        return grid_id_startswith_grid(col)

    @pa.check("ror_wikidata_id")
    def check_ror_wikidata_id(cls, col):
        return wikidata_id_startswith_Q(col)

    @pa.check("ror_url")
    def check_ror_url(cls, col):
        return str_startswith_http(col)

    @pa.check("ror_aliases")
    def check_ror_aliases(cls, col):
        return list_without_none(col)

    @pa.dataframe_check()
    def usa_state_code(cls, df):
        # Filter for US institutions only
        usa = df[df.ror_country_code == "US"]

        # If there are no US institutions, then something went wrong
        if usa.empty:
            return False

        return usa.ror_state_code.str.startswith("US-").all()


class WikidataDist(pa.DataFrameModel):
    @pa.check("wikidata_id")
    def check_wikidata_id(cls, col):
        return wikidata_id_startswith_Q(col)


class Wikidata(pa.DataFrameModel):
    @pa.check("wikidata_id")
    def check_wikidata_id(cls, col):
        return wikidata_id_startswith_Q(col)

    @pa.check("wikidata_grid_id")
    def check_wikidata_grid_id(cls, col):
        return grid_id_startswith_grid(col)

    @pa.check("wikidata_image")
    def check_wikidata_image(cls, col):
        return str_startswith_http(col)

    @pa.check("wikidata_url")
    def check_wikidata_url(cls, col):
        return str_startswith_http(col)

    @pa.check("wikidata_logo")
    def check_wikidata_logo(cls, col):
        return str_startswith_http(col)

    @pa.check("wikidata_unitid")
    def check_wikidata_unitid(cls, col):
        return unitid_above_minimum(col)

    @pa.check("wikidata_labels")
    def check_wikidata_labels(cls, col):
        return list_without_none(col)

    @pa.check("wikidata_lng")
    def check_wikidata_lng(cls, col):
        return longitude_within_range(col)

    @pa.check("wikidata_lat")
    def check_wikidata_lat(cls, col):
        return latitude_within_range(col)


class Wikipedia(pa.DataFrameModel):
    @pa.check("wikipedia_url")
    def check_wikipedia_url(cls, col):
        return (
            str_startswith_http(col).all()
            and wikipedia_url_contains_wikipedia(col).all()
        )

    @pa.check("wikipedia_image_url")
    def check_wikipedia_image_url(cls, col):
        return col.str.startswith("https://upload.wikimedia.org/wikipedia/")


class Schema(Dataset):
    # _id cannot be used w/ Pandera
    ror_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    grid_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    unitid: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    city: Series[pd.StringDtype]
    name: Series[pd.StringDtype]
    lat: Series[pd.Float64Dtype] = pa.Field(nullable=True)
    lng: Series[pd.Float64Dtype] = pa.Field(nullable=True)
    url: Series[pd.StringDtype] = pa.Field(nullable=True)
    country_code: Series[pd.StringDtype]
    country: Series[pd.StringDtype]
    state_code: Series[pd.StringDtype] = pa.Field(nullable=True)
    state: Series[pd.StringDtype] = pa.Field(nullable=True)
    enrollment: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    two_year: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    four_year: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    graduate: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    research: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    wikipedia_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    description: Series[pd.StringDtype] = pa.Field(nullable=True)
    image_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    names: Series[Object]
    urls: Series[Object]
