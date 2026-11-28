from dataclasses import dataclass, fields

from os_normalizer.institution import normalize_school_name
from os_normalizer.uri import (
    get_base_domain_url,
    get_domain_url,
    get_email_base_domain_url,
    get_email_domain_url,
    repair_url,
)

from os_institutions.matcher import format
from os_institutions.matcher.denylist import google_site_key, is_shared_host
from os_institutions.matcher.url_keys import path_prefix_keys


@dataclass
class Institution:
    _id: int
    grid_id: str | None
    ror_id: str | None
    wikidata_id: str | None
    unitid: int | None
    city: str | None
    name: str | None
    lat: float | None
    lng: float | None
    url: str | None
    country_code: str | None
    country: str | None
    state_code: str | None
    state: str | None
    enrollment: int | None
    two_year: bool | None
    four_year: bool | None
    graduate: bool | None
    research: bool | None
    wikipedia_url: str | None
    description: str | None
    image_url: str | None

    @classmethod
    def from_dict(cls, data: dict):
        if data and isinstance(data, dict):
            return cls(
                **{field.name: data.get(field.name) for field in fields(cls)}
            )


class InstitutionMatcher:
    @classmethod
    def load(cls, src: str):
        return cls(format.load(src))

    def __init__(self, table: dict):
        self.lookup_table = table.get("lookup", {})
        self.institutions = table.get("institutions", [])

    def __call__(
        self,
        *,
        url: str | None = None,
        source_url: str | None = None,
        email: str | None = None,
        school_name: str | None = None,
        wikidata_id: str | None = None,
        ror_id: str | None = None,
        grid_id: str | None = None,
        unitid: int | None = None,
    ):
        if match := self.match(
            url,
            source_url,
            email,
            school_name,
            wikidata_id,
            ror_id,
            grid_id,
            unitid,
        ):
            return Institution.from_dict(match)

    def lookup(self, key: str | None):
        if is_shared_host(key):
            return None
        if key and (idx := self.lookup_table.get(key)) is not None:
            if 0 <= idx < len(self.institutions):
                return self.institutions[idx]
        return None

    def lookup_path(self, url: str | None):
        """Longest registered path prefix of `url` (`d/a/b`, then `d/a`)."""
        for key in path_prefix_keys(url):
            if match := self.lookup(key):
                return match
        return None

    def match(
        self,
        url: str | None,
        source_url: str | None,
        email: str | None,
        school_name: str | None,
        wikidata_id: str | None,
        ror_id: str | None,
        grid_id: str | None,
        unitid: int | None = None,
    ):
        # Try all institution IDs in sequence
        if match := self.lookup(wikidata_id):
            return match
        if match := self.lookup(ror_id):
            return match
        if match := self.lookup(grid_id):
            return match
        if unitid is not None and (match := self.lookup(str(unitid))):
            return match

        # Before repair_url, which drops Google Sites URLs
        if match := self.lookup(google_site_key(url)):
            return match
        if match := self.lookup(google_site_key(source_url)):
            return match

        url = repair_url(url)
        source_url = repair_url(source_url)
        school_name = normalize_school_name(school_name)

        if match := self.lookup_path(url):
            return match
        if match := self.lookup_path(source_url):
            return match
        if match := self.lookup(get_domain_url(url)):
            return match
        if match := self.lookup(get_domain_url(source_url)):
            return match
        if match := self.lookup(school_name):
            return match
        if match := self.lookup(get_base_domain_url(url)):
            return match
        if match := self.lookup(get_base_domain_url(source_url)):
            return match
        if match := self.lookup(get_email_domain_url(email)):
            return match
        if match := self.lookup(get_email_base_domain_url(email)):
            return match
