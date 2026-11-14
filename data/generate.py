"""Build the synthetic AHDC database (data/ahdc.db).

Everything here is SYNTHETIC. Magnitudes are plausible so the demo reads credibly, but every value is
invented. The generator is seeded, so the output is the same on every run.

It plants the "traps" the demo and evals rely on (see tests/test_data_traps.py):
  * Region ambiguity: World Bank "Sub-Saharan Africa" (48) vs WHO "African Region" (47);
    ASEAN (11 since Timor-Leste joined in 2025) vs WHO South-East Asia Region vs UN South-eastern Asia.
  * Population weighting: the high-burden malaria countries are also the most populous, so a mean of country
    rates understates the regional rate. SSA 2025 is calibrated to 52.1 per 100k (2015: 78.4).
  * Provisional 2025 rows with wider uncertainty intervals.
  * Missing data: no 2025 malaria estimate for Eritrea or South Sudan; no TB estimate for Somalia 2003-2005.
  * Admin vs modeled vaccine coverage: India's admin DTP3 exceeds 100% in 2016-2018; a COVID dip in 2020-21.
  * USD vs PPP health spending; spending data stops at 2023.
  * Facility counts that need per-capita normalization and come only in irregular survey years.

Usage:  uv run python data/generate.py
"""

from __future__ import annotations

import csv
import math
import random
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "ahdc.db"
SEED = 20261116
YEARS = list(range(2000, 2026))
LATEST = 2025
EXPENDITURE_LATEST = 2023

rng = random.Random(SEED)


def lognorm(sd: float) -> float:
    return math.exp(rng.gauss(0, sd))


def interp(anchors: dict[int, float], year: int) -> float:
    """Piecewise-linear interpolation over {year: value} anchors."""
    ks = sorted(anchors)
    if year <= ks[0]:
        return anchors[ks[0]]
    if year >= ks[-1]:
        return anchors[ks[-1]]
    for a, b in zip(ks, ks[1:]):
        if a <= year <= b:
            return anchors[a] + (anchors[b] - anchors[a]) * (year - a) / (b - a)
    raise ValueError(year)


# ---------------------------------------------------------------------------------------------------------
# Countries
# ---------------------------------------------------------------------------------------------------------
def load_countries() -> list[dict]:
    with open(HERE / "seed" / "countries.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["pop_2025_m"] = float(r["pop_2025_m"])
        r["asean_join_year"] = int(r["asean_join_year"]) if r["asean_join_year"] else None
    return rows


SOUTHERN_HIGH_HIV = {"ZAF", "LSO", "SWZ", "BWA", "NAM", "MOZ", "ZMB", "ZWE", "MWI"}

# Malaria death rate per 100k around 2025, before calibration. Countries not listed have no malaria rows.
MALARIA_BASE = {
    # Sub-Saharan Africa
    "NGA": 95, "COD": 88, "NER": 105, "BFA": 80, "MLI": 78, "MOZ": 70, "UGA": 55, "CAF": 98, "TCD": 85,
    "SLE": 92, "GIN": 75, "BEN": 70, "CIV": 62, "CMR": 60, "GHA": 45, "TGO": 58, "LBR": 70, "GNB": 50,
    "GMB": 25, "BDI": 60, "AGO": 45, "ZMB": 40, "MWI": 42, "TZA": 33, "KEN": 22, "MDG": 30, "SSD": 75,
    "SDN": 15, "SOM": 18, "ERI": 8, "ETH": 8, "RWA": 12, "GNQ": 50, "GAB": 40, "COG": 45, "STP": 2,
    "SEN": 22, "MRT": 15, "ZWE": 15, "NAM": 3, "BWA": 1, "ZAF": 0.5, "SWZ": 1, "LSO": 0, "MUS": 0,
    "SYC": 0, "CPV": 0, "COM": 5,
    # Elsewhere
    "IND": 0.3, "PAK": 0.5, "AFG": 0.4, "BGD": 0.1, "MMR": 0.6, "IDN": 0.4, "PNG": 18, "SLB": 3, "VUT": 0.5,
    "KHM": 0.05, "LAO": 0.1, "PHL": 0.01, "VNM": 0.01, "THA": 0.03, "TLS": 0.0, "YEM": 3, "DJI": 2,
    "HTI": 0.5, "VEN": 0.3, "BRA": 0.02, "COL": 0.05, "PER": 0.02, "GUY": 1.5, "BOL": 0.01, "ECU": 0.01,
    "HND": 0.01, "NIC": 0.01, "GTM": 0.01, "PAN": 0.01, "SUR": 0.0,
}
# Malaria death-rate multiplier relative to 2025: steady decline, a stall after 2017, a COVID bump in 2020.
MALARIA_TREND = {2000: 2.6, 2005: 2.3, 2010: 1.8, 2015: 1.5, 2017: 1.4, 2019: 1.3, 2020: 1.38, 2021: 1.33,
                 2022: 1.18, 2023: 1.10, 2024: 1.05, 2025: 1.0}
MALARIA_SLOW_DECLINE = {"NGA": 0.85, "COD": 0.85}
MALARIA_TARGET_SSA = {2025: 52.1, 2015: 78.4}  # population-weighted, deaths per 100k
MALARIA_METHOD_UPDATE_2019 = ["BFA", "MLI", "NER", "TCD", "GIN", "SLE"]

TB_BASE = {"L": 38, "LM": 28, "UM": 7, "H": 0.7}
TB_FIXED = {"IND": 25, "IDN": 45, "PHL": 38, "MMR": 42, "PNG": 48, "PRK": 60, "PAK": 22, "BGD": 24}
TB_TREND = {2000: 1.9, 2010: 1.45, 2019: 1.08, 2020: 1.12, 2021: 1.15, 2022: 1.08, 2023: 1.03, 2024: 1.01,
            2025: 1.0}

HIV_SSA = {"ZAF": 140, "LSO": 230, "SWZ": 160, "BWA": 120, "MOZ": 150, "ZMB": 100, "ZWE": 110, "MWI": 70,
           "NAM": 90, "KEN": 45, "UGA": 50, "TZA": 48, "CMR": 40, "CIV": 30, "NGA": 24, "COD": 18,
           "ETH": 12, "GHA": 20, "CAF": 45, "GNQ": 35, "GAB": 30, "COG": 32, "SSD": 30, "RWA": 20, "BDI": 18}
HIV_OTHER = {"HTI": 9, "THA": 12, "UKR": 8, "RUS": 12, "BHS": 20, "JAM": 10}
HIV_BASE = {"L": 6, "LM": 3, "UM": 3.5, "H": 0.4}
HIV_TREND = {2000: 3.0, 2004: 3.6, 2008: 2.9, 2012: 2.0, 2016: 1.5, 2020: 1.2, 2025: 1.0}

MEASLES_BASE = {"L": 5, "LM": 1.5, "UM": 0.08, "H": 0.01}
MEASLES_TREND = {2000: 8.0, 2010: 2.5, 2019: 1.6, 2025: 1.0}
MEASLES_OUTBREAKS = {("COD", 2019): 5.0, ("MDG", 2019): 6.0}

DIARRHOEA_BASE = {"L": 55, "LM": 35, "UM": 7, "H": 2.5}

INCIDENCE_PER_DEATH = {"malaria": 400, "tuberculosis": None, "hiv_aids": 1.3, "measles": 60,
                       "diarrhoeal_diseases": 1000}
TB_INCIDENCE_PER_DEATH = {"L": 5, "LM": 5, "UM": 8, "H": 12}
REL_UNCERTAINTY = {"malaria": 0.20, "tuberculosis": 0.20, "hiv_aids": 0.25, "measles": 0.40,
                   "diarrhoeal_diseases": 0.30}

POP_GROWTH = {"L": 0.028, "LM": 0.018, "UM": 0.007, "H": 0.004}
POP_GROWTH_FIXED = {"CHN": 0.004, "JPN": -0.002, "KOR": 0.003, "IND": 0.013, "NGA": 0.026, "ETH": 0.027,
                    "COD": 0.032, "UKR": -0.006, "BLR": -0.003, "MDA": -0.008, "BGR": -0.007, "ROU": -0.005,
                    "SRB": -0.004, "BIH": -0.006, "LVA": -0.009, "LTU": -0.008, "RUS": -0.001, "USA": 0.007,
                    "GBR": 0.005, "DEU": 0.002, "ITA": -0.0005, "BRA": 0.008, "IDN": 0.011, "PAK": 0.021,
                    "BGD": 0.013, "TLS": 0.017}
U5_SHARE = {"L": 0.155, "LM": 0.11, "UM": 0.065, "H": 0.05}
LIFE_EXP = {"L": 62.0, "LM": 68.5, "UM": 75.5, "H": 81.0}
LIFE_EXP_GAIN_SINCE_2000 = {"L": 9.0, "LM": 6.0, "UM": 4.0, "H": 2.8}

# Vaccines: modeled 2019 DTP3 level by income group, and how much lower it was in 2000.
DTP3_2019 = {"L": 76, "LM": 86, "UM": 92, "H": 95}
DTP3_GAIN_SINCE_2000 = {"L": 30, "LM": 16, "UM": 6, "H": 2}
COVID_DIP = {2020: -3.0, 2021: -4.0, 2022: -1.5, 2023: -0.3}
INDIA_DTP3 = dict(zip(range(2015, 2026), [87, 88, 89, 90, 91, 86, 85, 92, 93, 93, 93]))
INDIA_MCV1 = dict(zip(range(2015, 2026), [83, 85, 87, 89, 90, 86, 84, 91, 92, 93, 93]))
INDIA_ADMIN_DTP3 = {2016: 102.4, 2017: 104.1, 2018: 101.3}

# Health spending, 2023 anchors (USD, PPP) per capita.
CHE_FIXED = {
    "SGP": (3640, 6120), "BRN": (800, 1950), "MYS": (480, 1250), "THA": (310, 850), "VNM": (180, 560),
    "IDN": (140, 450), "PHL": (190, 500), "TLS": (110, 250), "LAO": (60, 255), "KHM": (120, 380),
    "MMR": (50, 320), "USA": (13500, 13500), "CHE": (10500, 7800), "NOR": (9500, 8000), "DEU": (7000, 8100),
    "GBR": (5500, 6200), "JPN": (4100, 5600), "IND": (80, 290), "NGA": (70, 190), "CHN": (700, 1250),
}
CHE_USD = {"L": 40, "LM": 110, "UM": 520, "H": 4800}
PPP_FACTOR = {"L": 3.0, "LM": 3.0, "UM": 1.9, "H": 1.1}
CHE_GROWTH = {"L": 0.05, "LM": 0.06, "UM": 0.07, "H": 0.035}
CHE_PCT_GDP = {"L": 5.5, "LM": 4.5, "UM": 6.0, "H": 9.5}
OOP_PCT = {"L": 40, "LM": 45, "UM": 30, "H": 14}

FACILITY_YEARS = [2010, 2015, 2020, 2024]
HOSPITALS_PER_100K = {"L": 0.6, "LM": 1.0, "UM": 1.8, "H": 2.5}
CENTRES_PER_100K = {"L": 8, "LM": 12, "UM": 15, "H": 20}
BEDS_PER_1000 = {"L": 0.8, "LM": 1.2, "UM": 3.0, "H": 4.5}
BEDS_FIXED = {"JPN": 12.6, "KOR": 12.8, "DEU": 7.8, "USA": 2.8, "GBR": 2.4, "IND": 0.6}


SCHEMA = """
CREATE TABLE countries (
  iso3 TEXT PRIMARY KEY, name TEXT NOT NULL,
  wb_region TEXT NOT NULL, who_region TEXT NOT NULL, un_subregion TEXT NOT NULL,
  income_group TEXT NOT NULL, asean_join_year INTEGER, malaria_endemic INTEGER NOT NULL
);
CREATE TABLE demographics (
  iso3 TEXT NOT NULL REFERENCES countries(iso3), year INTEGER NOT NULL,
  population INTEGER NOT NULL, under5_population INTEGER NOT NULL, life_expectancy REAL NOT NULL,
  is_provisional INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (iso3, year)
);
CREATE TABLE disease_burden (
  iso3 TEXT NOT NULL REFERENCES countries(iso3), year INTEGER NOT NULL,
  cause TEXT NOT NULL, measure TEXT NOT NULL, metric TEXT NOT NULL,
  value REAL NOT NULL, lower REAL NOT NULL, upper REAL NOT NULL, is_provisional INTEGER NOT NULL,
  PRIMARY KEY (iso3, year, cause, measure, metric)
);
CREATE TABLE intervention_coverage (
  iso3 TEXT NOT NULL REFERENCES countries(iso3), year INTEGER NOT NULL,
  intervention TEXT NOT NULL, source TEXT NOT NULL, coverage_pct REAL NOT NULL, is_provisional INTEGER NOT NULL,
  PRIMARY KEY (iso3, year, intervention, source)
);
CREATE TABLE health_expenditure (
  iso3 TEXT NOT NULL REFERENCES countries(iso3), year INTEGER NOT NULL,
  che_per_capita_usd REAL NOT NULL, che_per_capita_ppp REAL NOT NULL, che_pct_gdp REAL NOT NULL, oop_pct REAL NOT NULL,
  PRIMARY KEY (iso3, year)
);
CREATE TABLE health_facilities (
  iso3 TEXT NOT NULL REFERENCES countries(iso3), year INTEGER NOT NULL,
  facility_type TEXT NOT NULL, facility_count INTEGER NOT NULL, beds INTEGER,
  PRIMARY KEY (iso3, year, facility_type)
);
CREATE TABLE data_notes (
  note_id INTEGER PRIMARY KEY, table_name TEXT NOT NULL, indicator TEXT, iso3 TEXT,
  year_from INTEGER, year_to INTEGER, note TEXT NOT NULL
);
CREATE INDEX ix_burden_cause ON disease_burden (cause, measure, metric, year);
CREATE INDEX ix_cov_int ON intervention_coverage (intervention, source, year);
CREATE INDEX ix_countries_wb ON countries (wb_region);
CREATE INDEX ix_countries_who ON countries (who_region);
"""


def build() -> dict:
    countries = load_countries()
    by_iso = {c["iso3"]: c for c in countries}
    ssa = [c["iso3"] for c in countries if c["wb_region"] == "Sub-Saharan Africa"]

    # ---- demographics -------------------------------------------------------------------------------------
    pop: dict[tuple[str, int], float] = {}
    demo_rows = []
    for c in countries:
        inc = c["income_group"]
        g = POP_GROWTH_FIXED.get(c["iso3"], POP_GROWTH[inc] + rng.uniform(-0.004, 0.004))
        le_2025 = LIFE_EXP[inc] + rng.gauss(0, 2.0)
        le_gain = LIFE_EXP_GAIN_SINCE_2000[inc] * rng.uniform(0.8, 1.2)
        for y in YEARS:
            p = c["pop_2025_m"] * 1e6 / (1 + g) ** (LATEST - y)
            pop[(c["iso3"], y)] = p
            u5 = p * U5_SHARE[inc] * (1 + 0.012 * (LATEST - y))
            le = le_2025 - le_gain * (LATEST - y) / 25
            if c["iso3"] in SOUTHERN_HIGH_HIV and y <= 2012:
                le -= 4.0 * math.sin(math.pi * (y - 2000) / 12) + 2.0
            if y in (2020, 2021):
                le -= 1.2 if y == 2021 else 0.8
            demo_rows.append((c["iso3"], y, round(p), round(u5), round(le, 1), int(y == LATEST)))

    # ---- disease burden (death rates first; counts, incidence and bounds derived) -------------------------
    rates: dict[tuple[str, int, str], float] = {}  # (iso3, year, cause) -> deaths per 100k

    for iso, base in MALARIA_BASE.items():
        slope = MALARIA_SLOW_DECLINE.get(iso, rng.uniform(0.85, 1.15))
        for y in YEARS:
            rates[(iso, y, "malaria")] = base * interp(MALARIA_TREND, y) ** slope * lognorm(0.03)

    for c in countries:
        iso, inc = c["iso3"], c["income_group"]
        tb = TB_FIXED.get(iso, TB_BASE[inc] * lognorm(0.25) * (2.2 if iso in SOUTHERN_HIGH_HIV else 1.0))
        hiv = HIV_SSA.get(iso) or HIV_OTHER.get(iso) or HIV_BASE[inc] * lognorm(0.4)
        mea = MEASLES_BASE[inc] * lognorm(0.5)
        dia = DIARRHOEA_BASE[inc] * lognorm(0.25)
        for y in YEARS:
            if not (iso == "SOM" and 2003 <= y <= 2005):
                rates[(iso, y, "tuberculosis")] = tb * interp(TB_TREND, y) * lognorm(0.03)
            rates[(iso, y, "hiv_aids")] = hiv * interp(HIV_TREND, y) * lognorm(0.03)
            spike = MEASLES_OUTBREAKS.get((iso, y)) or (3.0 if rng.random() < 0.03 else 1.0)
            rates[(iso, y, "measles")] = mea * interp(MEASLES_TREND, y) * spike * lognorm(0.08)
            rates[(iso, y, "diarrhoeal_diseases")] = dia * 2.2 ** ((LATEST - y) / 25) * lognorm(0.03)

    # Missing: no 2025 malaria estimate for Eritrea or South Sudan.
    for iso in ("ERI", "SSD"):
        del rates[(iso, LATEST, "malaria")]

    # Calibrate SSA malaria so the population-weighted rate hits the targets (2025 exactly, then 2015 via a
    # smooth correction that fades to 1 by 2025).
    def ssa_weighted(y: int) -> float:
        num = sum(rates[(i, y, "malaria")] * pop[(i, y)] for i in ssa if (i, y, "malaria") in rates)
        den = sum(pop[(i, y)] for i in ssa if (i, y, "malaria") in rates)
        return num / den

    f = MALARIA_TARGET_SSA[2025] / ssa_weighted(2025)
    for k in [k for k in rates if k[2] == "malaria" and k[0] in ssa]:
        rates[k] *= f
    c15 = MALARIA_TARGET_SSA[2015] / ssa_weighted(2015)
    for k in [k for k in rates if k[2] == "malaria" and k[0] in ssa]:
        y = k[1]
        rates[k] *= c15 if y <= 2015 else 1 + (c15 - 1) * (LATEST - y) / (LATEST - 2015)

    burden_rows = []
    for (iso, y, cause), r in rates.items():
        inc = by_iso[iso]["income_group"]
        prov = int(y == LATEST)
        if cause == "malaria":
            lo_u, hi_u = (0.263, 0.263 * 1.23) if prov else (0.20, 0.20 * 1.2)
        else:
            u = REL_UNCERTAINTY[cause] + (0.10 if prov else 0.0)
            lo_u, hi_u = u, u * 1.2
        inc_mult = INCIDENCE_PER_DEATH[cause] or TB_INCIDENCE_PER_DEATH[inc]
        for measure, rate in (("deaths", r), ("incidence", r * inc_mult)):
            count = rate * pop[(iso, y)] / 1e5
            for metric, v in (("count", count), ("rate_per_100k", rate)):
                nd = 0 if metric == "count" else 2
                burden_rows.append((iso, y, cause, measure, metric, round(v, nd), round(v * (1 - lo_u), nd),
                                    round(v * (1 + hi_u), nd), prov))

    # ---- intervention coverage ---------------------------------------------------------------------------
    cov_rows = []
    endemic_ssa = [i for i in ssa if MALARIA_BASE.get(i, 0) >= 5]
    for c in countries:
        iso, inc = c["iso3"], c["income_group"]
        d19 = min(98.5, DTP3_2019[inc] + rng.gauss(0, 4))
        gain = DTP3_GAIN_SINCE_2000[inc] * rng.uniform(0.7, 1.3)
        hepb_intro = rng.randint(2000, 2010)
        mcv2_intro = rng.randint(2000, 2016) if inc in ("L", "LM") else 2000
        admin_bias = rng.uniform(0.5, 6.0)
        for y in YEARS:
            dtp3 = d19 - gain * max(0, 2019 - y) / 19 + COVID_DIP.get(y, 0) * rng.uniform(0.6, 1.4)
            dtp3 = max(5.0, min(99.0, dtp3 + rng.gauss(0, 0.6)))
            mcv1 = max(5.0, min(99.0, dtp3 - 3 + rng.gauss(0, 1.5)))
            if iso == "IND":
                dtp3 = INDIA_DTP3.get(y, 58 + (86 - 58) * (y - 2000) / 14)
                mcv1 = INDIA_MCV1.get(y, 56 + (82 - 56) * (y - 2000) / 14)
            pol3 = max(5.0, min(99.0, dtp3 - 1 + rng.gauss(0, 1.0)))
            hepb = dtp3 * min(1.0, 0.4 + 0.6 * max(0, y - hepb_intro) / 6) - 1
            mcv2 = 0.0 if y < mcv2_intro else max(0.0, mcv1 - 15 * (1 - min(1, (y - mcv2_intro) / 8)) - 8)
            prov = int(y == LATEST)
            modeled = {"DTP3": dtp3, "MCV1": mcv1, "MCV2": mcv2, "Pol3": pol3, "HepB3": max(0.0, hepb)}
            for k, v in modeled.items():
                if k == "MCV2" and y < mcv2_intro:
                    continue
                cov_rows.append((iso, y, k, "modeled", round(v, 1), prov))
                admin = v + admin_bias + rng.gauss(0, 1.5)
                if iso == "IND" and k == "DTP3":
                    admin = INDIA_ADMIN_DTP3.get(y, min(99.5, v + rng.uniform(5, 9)))
                elif iso == "IND" and k == "MCV1" and y in INDIA_ADMIN_DTP3:
                    admin = INDIA_ADMIN_DTP3[y] - rng.uniform(1, 3)
                else:
                    admin = min(admin, 99.9)
                cov_rows.append((iso, y, k, "admin", round(admin, 1), prov))
            if iso in endemic_ssa:
                itn = interp({2000: 2, 2008: 25, 2015: 50, 2025: 58}, y) * rng.uniform(0.85, 1.15)
                cov_rows.append((iso, y, "ITN_use", "modeled", round(min(itn, 85), 1), prov))
            art_curve = {2000: 1, 2010: 25, 2025: 80} if c["wb_region"] == "Sub-Saharan Africa" else {2000: 10, 2010: 40, 2025: 75}
            art = interp(art_curve, y) * rng.uniform(0.85, 1.1)
            cov_rows.append((iso, y, "ART", "modeled", round(min(art, 97), 1), prov))

    # ---- health expenditure (through 2023 only) ----------------------------------------------------------
    exp_rows = []
    for c in countries:
        iso, inc = c["iso3"], c["income_group"]
        usd23, ppp23 = CHE_FIXED.get(iso) or (None, None)
        if usd23 is None:
            usd23 = CHE_USD[inc] * lognorm(0.35)
            ppp23 = usd23 * PPP_FACTOR[inc] * lognorm(0.15)
        gr = CHE_GROWTH[inc] * rng.uniform(0.8, 1.2)
        pct = CHE_PCT_GDP[inc] * lognorm(0.2) if iso != "USA" else 16.6
        oop = OOP_PCT[inc] * lognorm(0.25) if iso != "IND" else 47.0
        for y in range(2000, EXPENDITURE_LATEST + 1):
            covid = 1.06 if y in (2020, 2021) else 1.0
            k = (1 + gr) ** (EXPENDITURE_LATEST - y)
            exp_rows.append((iso, y, round(usd23 / k * covid * lognorm(0.01), 0),
                             round(ppp23 / k * covid * lognorm(0.01), 0),
                             round(pct * covid * lognorm(0.03), 1),
                             round(min(85.0, oop * (1 + 0.01 * (EXPENDITURE_LATEST - y))), 1)))

    # ---- health facilities (irregular survey years) --------------------------------------------------------
    fac_rows = []
    for c in countries:
        iso, inc = c["iso3"], c["income_group"]
        h100 = HOSPITALS_PER_100K[inc] * lognorm(0.3)
        c100 = CENTRES_PER_100K[inc] * lognorm(0.3)
        beds = BEDS_FIXED.get(iso, BEDS_PER_1000[inc] * lognorm(0.3))
        for y in FACILITY_YEARS:
            if y != 2020 and rng.random() < 0.15:
                continue
            p = pop[(iso, y)]
            growth = 1 + 0.01 * (y - 2010)
            fac_rows.append((iso, y, "hospital", max(1, round(h100 * p / 1e5 * growth)), round(beds * p / 1000)))
            fac_rows.append((iso, y, "health_centre", max(1, round(c100 * p / 1e5 * growth)), None))

    # ---- notes ---------------------------------------------------------------------------------------------
    notes = [
        ("*", None, None, None, None, "ALL DATA IN THIS DATABASE ARE SYNTHETIC. Values are invented for a prototype demo and must not be used for analysis or decisions."),
        ("disease_burden", None, None, 2025, 2025, "2025 estimates are provisional and will be revised in the next annual release. Uncertainty intervals are wider for 2025."),
        ("disease_burden", "malaria", "ERI", 2025, 2025, "No 2025 malaria estimate for Eritrea (reporting incomplete)."),
        ("disease_burden", "malaria", "SSD", 2025, 2025, "No 2025 malaria estimate for South Sudan (reporting incomplete)."),
        ("disease_burden", "tuberculosis", "SOM", 2003, 2005, "No tuberculosis estimates for Somalia 2003-2005 because of data gaps."),
        ("disease_burden", "measles", "COD", 2019, 2019, "Large measles outbreak in 2019."),
        ("disease_burden", "measles", "MDG", 2019, 2019, "Large measles outbreak in 2019."),
        ("disease_burden", None, None, None, None, "Rates (metric = 'rate_per_100k') are country-level. To aggregate across countries, sum counts and divide by summed population from demographics; do not average country rates."),
        ("intervention_coverage", None, None, None, None, "source = 'modeled' are harmonized estimates and are preferred for trends and comparisons. source = 'admin' are country-reported figures (doses given / estimated target population) and can be biased upward."),
        ("intervention_coverage", "DTP3", "IND", 2016, 2018, "Administrative DTP3 coverage exceeds 100% in 2016-2018 because of denominator problems (outdated target-population estimates). Use modeled estimates for trends."),
        ("intervention_coverage", None, None, 2020, 2022, "Routine immunization fell in many countries in 2020-2021 because of COVID-19 service disruptions."),
        ("intervention_coverage", None, None, 2025, 2025, "2025 coverage estimates are provisional."),
        ("health_expenditure", None, None, None, None, "Latest available year is 2023. Values are current health expenditure (CHE) per capita, in current US dollars and in current international dollars (PPP). Use PPP for cross-country comparisons of purchasing power."),
        ("health_facilities", None, None, None, None, "Facility data come from periodic surveys (2010, 2015, 2020, 2024); not every country reports every survey year. Counts are absolute: normalize by population before comparing countries."),
        ("countries", "region", None, None, None, "Region schemes differ. World Bank 'Sub-Saharan Africa' (48 countries) includes Sudan and Somalia; WHO 'African Region' (47) includes Algeria but not Sudan or Somalia. 'Southeast Asia' can mean ASEAN members, the UN 'South-eastern Asia' subregion, or the WHO 'South-East Asia Region' (which includes India and Bangladesh). State which scheme is used."),
        ("countries", "asean", "TLS", 2025, 2025, "Timor-Leste became the 11th ASEAN member in October 2025 (asean_join_year = 2025)."),
    ]
    for iso in MALARIA_METHOD_UPDATE_2019:
        notes.append(("disease_burden", "malaria", iso, 2019, 2019, "Estimation method updated in 2019; values for 2000-2018 were back-cast with the new method."))

    # ---- write ---------------------------------------------------------------------------------------------
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO countries VALUES (?,?,?,?,?,?,?,?)",
                    [(c["iso3"], c["name"], c["wb_region"], c["who_region"], c["un_subregion"], c["income_group"],
                      c["asean_join_year"], int(MALARIA_BASE.get(c["iso3"], 0) > 0)) for c in countries])
    con.executemany("INSERT INTO demographics VALUES (?,?,?,?,?,?)", demo_rows)
    con.executemany("INSERT INTO disease_burden VALUES (?,?,?,?,?,?,?,?,?)", burden_rows)
    con.executemany("INSERT INTO intervention_coverage VALUES (?,?,?,?,?,?)", cov_rows)
    con.executemany("INSERT INTO health_expenditure VALUES (?,?,?,?,?,?)", exp_rows)
    con.executemany("INSERT INTO health_facilities VALUES (?,?,?,?,?)", fac_rows)
    con.executemany("INSERT INTO data_notes (table_name, indicator, iso3, year_from, year_to, note) VALUES (?,?,?,?,?,?)", notes)
    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("countries", "demographics", "disease_burden", "intervention_coverage",
                        "health_expenditure", "health_facilities", "data_notes")}
    con.close()
    return counts


if __name__ == "__main__":
    counts = build()
    print(f"Wrote {DB_PATH}")
    for t, n in counts.items():
        print(f"  {t:<22} {n:>7,} rows")
