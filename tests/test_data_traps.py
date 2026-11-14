"""Checks that the synthetic database contains the traps the demo and evals depend on."""

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "ahdc.db"


def regenerate() -> None:
    subprocess.run([sys.executable, str(ROOT / "data" / "generate.py")], check=True, capture_output=True)


@pytest.fixture(scope="module")
def con():
    if not DB.exists():
        regenerate()
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    yield c
    c.close()


def q(con, sql, *args):
    return con.execute(sql, args).fetchall()


def members(con, where):
    return {r[0] for r in q(con, f"SELECT iso3 FROM countries WHERE {where}")}


# --- regions -------------------------------------------------------------------------------------------------
def test_region_schemes_disagree(con):
    assert len(q(con, "SELECT * FROM countries")) >= 150
    ssa = members(con, "wb_region = 'Sub-Saharan Africa'")
    afr = members(con, "who_region = 'African Region'")
    assert len(ssa) == 48 and len(afr) == 47
    assert afr - ssa == {"DZA"}
    assert ssa - afr == {"SDN", "SOM"}


def test_southeast_asia_is_ambiguous(con):
    asean = members(con, "asean_join_year IS NOT NULL")
    asean_2023 = members(con, "asean_join_year <= 2023")
    un = members(con, "un_subregion = 'South-eastern Asia'")
    sear = members(con, "who_region = 'South-East Asia Region'")
    assert len(asean) == 11 and "TLS" in asean and "TLS" not in asean_2023
    assert un == asean
    assert {"IND", "BGD"} <= sear and "SGP" not in sear


# --- malaria / population weighting ----------------------------------------------------------------------
SSA_MALARIA = """
SELECT COUNT(*), 1e5 * SUM(b.value) / SUM(d.population), 1e5 * SUM(b.lower) / SUM(d.population),
       1e5 * SUM(b.upper) / SUM(d.population)
FROM disease_burden b JOIN demographics d USING (iso3, year) JOIN countries c USING (iso3)
WHERE c.wb_region = 'Sub-Saharan Africa' AND b.cause = 'malaria' AND b.measure = 'deaths'
  AND b.metric = 'count' AND b.year = ?
"""


def test_ssa_malaria_2025_population_weighted(con):
    n, rate, lo, hi = q(con, SSA_MALARIA, 2025)[0]
    assert n == 46
    assert rate == pytest.approx(52.1, abs=0.05)
    assert lo == pytest.approx(38.4, abs=0.1) and hi == pytest.approx(69.0, abs=0.1)
    (unweighted,) = q(con, """SELECT AVG(value) FROM disease_burden b JOIN countries c USING (iso3)
        WHERE c.wb_region = 'Sub-Saharan Africa' AND cause = 'malaria' AND measure = 'deaths'
          AND metric = 'rate_per_100k' AND year = 2025""")[0]
    assert unweighted < rate - 8, "a mean of country rates must visibly understate the weighted rate"


def test_ssa_malaria_2015(con):
    n, rate, _, _ = q(con, SSA_MALARIA, 2015)[0]
    assert n == 48 and rate == pytest.approx(78.4, abs=0.05)


def test_missing_malaria_2025(con):
    have = {r[0] for r in q(con, """SELECT DISTINCT iso3 FROM disease_burden WHERE cause = 'malaria'
        AND year = 2025""")}
    ssa = members(con, "wb_region = 'Sub-Saharan Africa'")
    assert ssa - have == {"ERI", "SSD"}
    notes = q(con, "SELECT iso3 FROM data_notes WHERE indicator = 'malaria' AND year_from = 2025")
    assert {r[0] for r in notes} == {"ERI", "SSD"}


def test_somalia_tb_gap(con):
    years = {r[0] for r in q(con, "SELECT DISTINCT year FROM disease_burden WHERE iso3 = 'SOM' AND cause = 'tuberculosis'")}
    assert not years & {2003, 2004, 2005} and {2002, 2006} <= years


def test_counts_and_rates_agree(con):
    rows = q(con, """SELECT c.value, r.value, d.population FROM disease_burden c
        JOIN disease_burden r ON r.iso3 = c.iso3 AND r.year = c.year AND r.cause = c.cause
         AND r.measure = c.measure AND r.metric = 'rate_per_100k'
        JOIN demographics d ON d.iso3 = c.iso3 AND d.year = c.year
        WHERE c.metric = 'count' AND c.value > 1000 LIMIT 500""")
    for count, rate, pop in rows:
        assert count / pop * 1e5 == pytest.approx(rate, rel=0.01)


# --- provisional -------------------------------------------------------------------------------------------
def test_provisional_flags(con):
    assert q(con, "SELECT COUNT(*) FROM disease_burden WHERE is_provisional = 1 AND year <> 2025")[0][0] == 0
    assert q(con, "SELECT COUNT(*) FROM disease_burden WHERE is_provisional = 0 AND year = 2025")[0][0] == 0
    w24, w25 = (q(con, """SELECT AVG((upper - lower) / value) FROM disease_burden
        WHERE cause = 'malaria' AND metric = 'count' AND value > 0 AND year = ?""", y)[0][0] for y in (2024, 2025))
    assert w25 > w24 * 1.2


# --- vaccination -------------------------------------------------------------------------------------------
def test_india_dtp3(con):
    modeled = dict(q(con, "SELECT year, coverage_pct FROM intervention_coverage WHERE iso3 = 'IND' AND intervention = 'DTP3' AND source = 'modeled'"))
    admin = dict(q(con, "SELECT year, coverage_pct FROM intervention_coverage WHERE iso3 = 'IND' AND intervention = 'DTP3' AND source = 'admin'"))
    assert (modeled[2015], modeled[2021], modeled[2025]) == (87, 85, 93)
    assert modeled[2021] < modeled[2019] < modeled[2022]
    assert {y for y, v in admin.items() if v > 100} == {2016, 2017, 2018}


# --- spending ----------------------------------------------------------------------------------------------
def test_health_expenditure_usd_vs_ppp(con):
    assert q(con, "SELECT MAX(year) FROM health_expenditure")[0][0] == 2023
    usd = dict(q(con, """SELECT iso3, che_per_capita_usd FROM health_expenditure JOIN countries USING (iso3)
        WHERE asean_join_year <= 2023 AND year = 2023"""))
    ppp = dict(q(con, """SELECT iso3, che_per_capita_ppp FROM health_expenditure JOIN countries USING (iso3)
        WHERE asean_join_year <= 2023 AND year = 2023"""))
    assert len(usd) == 10
    assert max(usd.values()) / min(usd.values()) > 50
    assert max(ppp.values()) / min(ppp.values()) < 30
    assert max(usd, key=usd.get) == "SGP" and min(usd, key=usd.get) == "MMR"


# --- facilities --------------------------------------------------------------------------------------------
def test_facilities_irregular_but_2020_complete(con):
    n_countries = q(con, "SELECT COUNT(*) FROM countries")[0][0]
    assert q(con, "SELECT COUNT(DISTINCT iso3) FROM health_facilities WHERE year = 2020")[0][0] == n_countries
    assert q(con, "SELECT COUNT(DISTINCT iso3) FROM health_facilities WHERE year = 2015")[0][0] < n_countries


# --- dictionary matches schema -----------------------------------------------------------------------------
def test_dictionary_matches_schema(con):
    dd = yaml.safe_load((ROOT / "data" / "data_dictionary.yaml").read_text())
    tables = {r[0] for r in q(con, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == set(dd["tables"])
    for t in tables:
        cols = {r[1] for r in q(con, f"PRAGMA table_info({t})")}
        assert cols == set(dd["tables"][t]["columns"]), t


# --- reproducibility ---------------------------------------------------------------------------------------
def test_generator_is_deterministic():
    def table_digest() -> str:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        h = hashlib.sha256()
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"):
            for row in c.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3"):
                h.update(repr(row).encode())
        c.close()
        return h.hexdigest()

    before = table_digest()
    regenerate()
    assert table_digest() == before
