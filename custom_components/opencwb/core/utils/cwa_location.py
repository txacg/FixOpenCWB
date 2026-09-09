"""Explicit F-D0047 routing, with stored configuration values left unchanged."""

from dataclasses import dataclass
from urllib.parse import unquote_plus

from ..commons.location_tw import LOCATIONS
from .cwa_forecast import ForecastType

# county, short-term dataset, 12-hour dataset (CWA /apidoc/v1)
DATASETS = (
    ("宜蘭縣", "001", "003"),
    ("桃園市", "005", "007"),
    ("新竹縣", "009", "011"),
    ("苗栗縣", "013", "015"),
    ("彰化縣", "017", "019"),
    ("南投縣", "021", "023"),
    ("雲林縣", "025", "027"),
    ("嘉義縣", "029", "031"),
    ("屏東縣", "033", "035"),
    ("臺東縣", "037", "039"),
    ("花蓮縣", "041", "043"),
    ("澎湖縣", "045", "047"),
    ("基隆市", "049", "051"),
    ("新竹市", "053", "055"),
    ("嘉義市", "057", "059"),
    ("臺北市", "061", "063"),
    ("高雄市", "065", "067"),
    ("新北市", "069", "071"),
    ("臺中市", "073", "075"),
    ("臺南市", "077", "079"),
    ("連江縣", "081", "083"),
    ("金門縣", "085", "087"),
)


@dataclass(frozen=True)
class CwaLocation:
    dataset: str
    name: str
    county: str


def forecast_type_for_mode(mode: str) -> ForecastType:
    if mode in ("daily", "onecall_daily"):
        return "twice_daily"
    if mode in ("hourly", "onecall_hourly"):
        return "hourly"
    raise ValueError("Unsupported forecast mode")


def resolve_location(name: str, forecast_type: ForecastType) -> CwaLocation:
    if not isinstance(name, str) or forecast_type not in ("hourly", "twice_daily"):
        raise ValueError("Invalid location or forecast type")
    normalized = unquote_plus(name).strip().replace("台", "臺")
    counties = {county for county, _, _ in DATASETS}
    if normalized in counties:
        return CwaLocation(
            "F-D0047-089" if forecast_type == "hourly" else "F-D0047-091",
            normalized,
            normalized,
        )
    matches = []
    for county, hourly, weekly in DATASETS:
        for encoded in LOCATIONS[f"F-D0047-{hourly}"]:
            town = unquote_plus(encoded).removeprefix(county)
            if normalized in (town, county + town):
                matches.append(
                    CwaLocation(
                        f"F-D0047-{hourly if forecast_type == 'hourly' else weekly}",
                        town,
                        county,
                    )
                )
    if len(matches) != 1:
        raise ValueError("Unknown or ambiguous location; include the county/city")
    return matches[0]
