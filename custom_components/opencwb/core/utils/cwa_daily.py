"""Read CWA's official Week24 XML without synthesizing daily values."""

from datetime import datetime
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from .cwa_forecast import CwaDataError, CwaForecast, parse_forecast, parse_timestamp


def parse_daily_xml(raw: bytes) -> dict[str, tuple[CwaForecast, datetime]]:
    try:
        text = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise CwaDataError("DTD/entity declarations are not accepted in CWA XML")
        root = ET.fromstring(text)
        for node in root.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
        issued = parse_timestamp(root.findtext("Sent"))
        result = {}
        for group in root.iter("Locations"):
            county = group.findtext("LocationsName", "").replace("台", "臺")
            for loc in group.findall("Location"):
                name = loc.findtext("LocationName", "").replace("台", "臺")
                elements = []
                for element in loc.findall("WeatherElement"):
                    rows = []
                    for time in element.findall("Time"):
                        rows.append(
                            {
                                "StartTime": time.findtext("StartTime"),
                                "EndTime": time.findtext("EndTime"),
                                "ElementValue": [
                                    {child.tag: child.text for child in value}
                                    for value in time.findall("ElementValue")
                                ],
                            }
                        )
                    elements.append(
                        {"ElementName": element.findtext("ElementName"), "Time": rows}
                    )
                payload = {
                    "success": True,
                    "records": {
                        "Locations": [
                            {
                                "Location": [
                                    {
                                        "LocationName": name,
                                        "Latitude": loc.findtext("Latitude"),
                                        "Longitude": loc.findtext("Longitude"),
                                        "WeatherElement": elements,
                                    }
                                ]
                            }
                        ]
                    },
                }
                canonical = (
                    name
                    if county in ("臺灣", "臺灣各縣市") or name == county
                    else county + name
                )
                result[canonical] = (parse_forecast(payload, name, "daily"), issued)
        if not result:
            raise CwaDataError("Missing CWA daily locations")
        return result
    except (ET.ParseError, UnicodeError, TypeError, ValueError) as error:
        if isinstance(error, CwaDataError):
            raise
        raise CwaDataError("Malformed CWA daily XML") from None


def parse_daily_archive(raw: bytes) -> dict[str, tuple[CwaForecast, datetime]]:
    """Bound both compressed and expanded data; never extract to the filesystem."""
    if len(raw) > 16_000_000:
        raise CwaDataError("CWA archive exceeds size limit")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = [
                m for m in archive.infolist() if m.filename.endswith("_Week24_CH.xml")
            ]
            if (
                not members
                or len(members) > 30
                or sum(m.file_size for m in members) > 64_000_000
            ):
                raise CwaDataError("Invalid CWA daily archive contents")
            result = {}
            for member in members:
                if member.file_size > 8_000_000:
                    raise CwaDataError("CWA XML exceeds size limit")
                for name, value in parse_daily_xml(archive.read(member)).items():
                    if name in result:
                        raise CwaDataError("Duplicate CWA daily location")
                    result[name] = value
            return result
    except (BadZipFile, RuntimeError, KeyError, OSError, ZlibError):
        raise CwaDataError("Malformed CWA daily archive") from None
