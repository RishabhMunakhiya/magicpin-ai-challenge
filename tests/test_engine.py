from __future__ import annotations

import json
from pathlib import Path
import pytest
from vera_engine import engine
from validators import validate_no_urls, check_taboos

DATASET_DIR = Path(__file__).parent.parent / "dataset"


@pytest.fixture(scope="module")
def dataset():
    categories = {}
    for f in (DATASET_DIR / "categories").glob("*.json"):
        data = json.load(open(f))
        categories[data["slug"]] = data
    merchants = {m["merchant_id"]: m for m in json.load(open(DATASET_DIR / "merchants_seed.json"))["merchants"]}
    customers = {c["customer_id"]: c for c in json.load(open(DATASET_DIR / "customers_seed.json"))["customers"]}
    triggers = {t["id"]: t for t in json.load(open(DATASET_DIR / "triggers_seed.json"))["triggers"]}
    return {"categories": categories, "merchants": merchants, "customers": customers, "triggers": triggers}


def test_dentist_research_digest(dataset):
    cat = dataset["categories"]["dentists"]
    m = dataset["merchants"]["m_001_drmeera_dentist_delhi"]
    trg = dataset["triggers"]["trg_001_research_digest_dentists"]
    
    composed = engine.compose(category=cat, merchant=m, trigger=trg, customer=None)
    assert composed.send_as == "vera"
    assert "Dr. Meera" in composed.body
    assert "JIDA" in composed.body
    assert "38%" in composed.body
    assert validate_no_urls(composed.body)
    assert not check_taboos(composed.body, cat.get("voice", {}).get("vocab_taboo", []))


def test_dentist_recall_priya(dataset):
    cat = dataset["categories"]["dentists"]
    m = dataset["merchants"]["m_001_drmeera_dentist_delhi"]
    c = dataset["customers"]["c_001_priya_for_m001"]
    trg = dataset["triggers"]["trg_003_recall_due_priya"]

    composed = engine.compose(category=cat, merchant=m, trigger=trg, customer=c)
    assert composed.send_as == "merchant_on_behalf"
    assert "Priya" in composed.body
    assert "₹299" in composed.body
    assert validate_no_urls(composed.body)


def test_salon_bridal_kavya(dataset):
    cat = dataset["categories"]["salons"]
    m = dataset["merchants"]["m_003_studio11_salon_hyderabad"]
    c = dataset["customers"]["c_005_kavya_for_m003"]
    trg = dataset["triggers"]["trg_007_bridal_followup_kavya"]

    composed = engine.compose(category=cat, merchant=m, trigger=trg, customer=c)
    assert composed.send_as == "merchant_on_behalf"
    assert "Kavya" in composed.body
    assert "196 days" in composed.body or "wedding" in composed.body.lower()
    assert validate_no_urls(composed.body)


def test_restaurant_ipl_saturday(dataset):
    cat = dataset["categories"]["restaurants"]
    m = dataset["merchants"]["m_005_pizzajunction_restaurant_delhi"]
    trg = dataset["triggers"]["trg_010_ipl_match_delhi"]

    composed = engine.compose(category=cat, merchant=m, trigger=trg, customer=None)
    assert composed.send_as == "vera"
    assert "Suresh" in composed.body
    assert "-12%" in composed.body or "BOGO" in composed.body
    assert validate_no_urls(composed.body)


def test_gym_seasonal_dip(dataset):
    cat = dataset["categories"]["gyms"]
    m = dataset["merchants"]["m_007_powerhouse_gym_bangalore"]
    trg = dataset["triggers"]["trg_014_seasonal_acquisition_dip_powerhouse"]

    composed = engine.compose(category=cat, merchant=m, trigger=trg, customer=None)
    assert composed.send_as == "vera"
    assert "Karthik" in composed.body
    assert "April-June" in composed.body or "30%" in composed.body
    assert validate_no_urls(composed.body)


def test_pharmacy_atorvastatin_recall(dataset):
    cat = dataset["categories"]["pharmacies"]
    m = dataset["merchants"]["m_009_apollo_pharmacy_jaipur"]
    trg = dataset["triggers"]["trg_018_supply_atorvastatin_recall"]

    composed = engine.compose(category=cat, merchant=m, trigger=trg, customer=None)
    assert composed.send_as == "vera"
    assert "Ramesh" in composed.body
    assert "AT2024-1102" in composed.body
    assert validate_no_urls(composed.body)


def test_pharmacy_chronic_refill_sharma(dataset):
    cat = dataset["categories"]["pharmacies"]
    m = dataset["merchants"]["m_009_apollo_pharmacy_jaipur"]
    c = dataset["customers"]["c_013_grandfather_for_m009"]
    trg = dataset["triggers"]["trg_019_chronic_refill_grandfather"]

    composed = engine.compose(category=cat, merchant=m, trigger=trg, customer=c)
    assert composed.send_as == "merchant_on_behalf"
    assert "Sharma" in composed.body
    assert "metformin" in composed.body
    assert "15%" in composed.body or "₹1,420" in composed.body
    assert validate_no_urls(composed.body)
