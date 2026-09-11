from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from core.utils.cwa_daily import parse_daily_archive, parse_daily_xml
from core.utils.cwa_forecast import CwaDataError, to_ha_forecast


def xml():
    return (Path(__file__).parent / "fixtures/yonghe_daily.xml").read_bytes()


def test_official_daily_values_and_calendar_days():
    data, issued = parse_daily_xml(xml())["新北市永和區"]
    assert len(data.periods) == 7
    first = to_ha_forecast(data.periods[0], "daily")
    assert first["datetime"] == "2026-09-11T16:00:00+00:00"
    assert first["native_temperature"] == 32
    assert first["native_templow"] == 25
    assert "is_daytime" not in first and "native_precipitation" not in first
    assert len({p.start.date() for p in data.periods}) == 7
    assert issued.isoformat() == "2026-09-11T10:15:47+00:00"


def test_daily_archive_selects_only_official_chinese_day_product():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("65_Week24_CH.xml", xml())
        archive.writestr("65_Weekday_CH.xml", b"not daily")
    assert "新北市永和區" in parse_daily_archive(buffer.getvalue())


@pytest.mark.parametrize(
    "raw", [b"", b"<bad", b'<!DOCTYPE a [<!ENTITY x "bad">]><a>&x;</a>']
)
def test_invalid_or_entity_xml_rejected(raw):
    with pytest.raises(CwaDataError):
        parse_daily_xml(raw)


def test_invalid_archive_and_interval_rejected():
    with pytest.raises(CwaDataError):
        parse_daily_archive(b"not zip")
    with pytest.raises(CwaDataError):
        parse_daily_xml(xml().replace(b"2026-09-12T00:00:00", b"2026-09-12T06:00:00"))
