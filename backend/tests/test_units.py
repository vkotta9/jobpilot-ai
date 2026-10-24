"""Unit tests: parsing, adapters, matching, tailoring fact guard."""
import json

import httpx
import pytest

from app.models import CandidateProfile, Job
from app.services import resume_parser
from app.services.matching import assess, candidate_evidence_text
from app.services.sources import SourceError
from app.services.sources.greenhouse import GreenhouseAdapter
from app.services.sources.lever import LeverAdapter
from app.services.tailoring import cover_letter, fact_guard, tailor_resume, unresolved_placeholders, validate_resume_edit
from app.services.textutil import find_skills, job_fingerprint, years_of_experience

from .conftest import SAMPLE_PROFILE, sample_docx_bytes, sample_pdf_bytes


def profile_obj(**kw):
    data = {k: v for k, v in SAMPLE_PROFILE.items() if k != "confirm"}
    data["match_weights"] = {}
    data.update(kw)
    return CandidateProfile(user_id=1, **data)


def job_obj(**kw):
    base = dict(id=1, user_id=1, source_kind="manual", external_id="x", fingerprint="f", title="Senior Backend Engineer",
                company="Globex", location="New York, NY", remote_type="hybrid", listing_status="active", is_simulated=False,
                description_text="5+ years of experience with Python, FastAPI, PostgreSQL, Kubernetes and AWS.",
                salary_min=150000, salary_max=180000, salary_interval="per-year-salary")
    base.update(kw)
    return Job(**base)


# ---------------------------------------------------------------- parsing

def test_docx_parse_extracts_structure():
    data = sample_docx_bytes()
    assert resume_parser.validate_upload("cv.docx", data, 5_000_000) == "docx"
    p = resume_parser.parse_resume_text(resume_parser.extract_text("docx", data))
    assert p["full_name"] == "Jordan Rivera"
    assert p["email"] == "jordan@example.com"
    assert len(p["experience"]) == 2
    assert p["experience"][0]["company"] == "Acme Corp"
    assert p["experience"][0]["title"] == "Senior Software Engineer"
    assert p["experience"][0]["start"] == "Jan 2020" and p["experience"][0]["end"] == "Present"
    assert any("payments API" in b for b in p["experience"][0]["bullets"])
    assert "Python" in p["skills"]
    assert p["education"] and "Computer Science" in p["education"][0]["degree"]


def test_pdf_parse():
    data = sample_pdf_bytes()
    assert resume_parser.validate_upload("cv.pdf", data, 5_000_000) == "pdf"
    p = resume_parser.parse_resume_text(resume_parser.extract_text("pdf", data))
    assert p["email"] == "jordan@example.com"
    assert p["experience"] and p["experience"][0]["company"] == "Acme Corp"


@pytest.mark.parametrize("name,data,msg", [
    ("cv.pdf", b"not a pdf at all", "not a valid PDF"),
    ("cv.docx", b"%PDF-1.4 fake", "not a valid DOCX"),
    ("cv.exe", b"MZ....", "Only PDF and DOCX"),
    ("cv.pdf", b"", "empty"),
])
def test_upload_validation_rejects(name, data, msg):
    with pytest.raises(resume_parser.UploadError, match=msg):
        resume_parser.validate_upload(name, data, 5_000_000)


def test_upload_size_limit():
    with pytest.raises(resume_parser.UploadError, match="too large"):
        resume_parser.validate_upload("cv.pdf", b"%PDF" + b"0" * 2000, 1000)


# ---------------------------------------------------------------- adapters

GH_PAYLOAD = {"jobs": [{
    "id": 4012345, "title": "Senior Backend Engineer", "updated_at": "2026-10-01T12:00:00-04:00",
    "location": {"name": "New York, NY"}, "absolute_url": "https://job-boards.greenhouse.io/globex/jobs/4012345",
    "departments": [{"id": 1, "name": "Engineering"}], "offices": [],
    "content": "&lt;p&gt;We need &lt;strong&gt;Python&lt;/strong&gt; and AWS.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;5+ years&lt;/li&gt;&lt;/ul&gt;",
    "metadata": [{"name": "Employment Type", "value": "Full-time"}]}], "meta": {"total": 1}}

LEVER_PAYLOAD = [{
    "id": "abc-123", "text": "Senior Backend Engineer", "categories": {"location": "New York, NY", "commitment": "Full-time", "team": "Platform"},
    "descriptionPlain": "Build APIs in Python.", "lists": [{"text": "Requirements", "content": "<li>PostgreSQL</li><li>Docker</li>"}],
    "additionalPlain": "", "hostedUrl": "https://jobs.lever.co/globex/abc-123", "applyUrl": "https://jobs.lever.co/globex/abc-123/apply",
    "createdAt": 1790000000000, "workplaceType": "hybrid", "salaryRange": {"currency": "USD", "interval": "per-year-salary", "min": 150000, "max": 190000}}]


def transport_for(routes):
    def handler(req: httpx.Request):
        for prefix, (status, body, ctype) in routes.items():
            if str(req.url).startswith(prefix):
                content = body if isinstance(body, (bytes, str)) else json.dumps(body)
                return httpx.Response(status, content=content, headers={"content-type": ctype})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def test_greenhouse_adapter_normalizes():
    t = transport_for({
        "https://boards-api.greenhouse.io/v1/boards/globex/jobs": (200, GH_PAYLOAD, "application/json"),
        "https://boards-api.greenhouse.io/v1/boards/globex": (200, {"name": "Globex"}, "application/json"),
    })
    jobs = GreenhouseAdapter("globex", transport=t, sleep=lambda s: None).fetch()
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Globex" and j.external_id == "4012345"
    assert "Python" in j.description_text and "<" not in j.description_text
    assert j.apply_url.startswith("https://job-boards.greenhouse.io/")
    assert j.employment_type == "Full-time" and j.department == "Engineering"


def test_lever_adapter_normalizes():
    t = transport_for({"https://api.lever.co/v0/postings/globex": (200, LEVER_PAYLOAD, "application/json")})
    j = LeverAdapter("globex", transport=t, sleep=lambda s: None).fetch()[0]
    assert j.remote_type == "hybrid" and j.salary_min == 150000
    assert "PostgreSQL" in j.description_text
    assert j.apply_url.endswith("/apply") and j.posted_at is not None


def test_adapter_404_is_clear_error():
    t = transport_for({})
    with pytest.raises(SourceError, match="not found"):
        GreenhouseAdapter("nope", transport=t, sleep=lambda s: None).fetch()


def test_adapter_retries_rate_limit_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, json=LEVER_PAYLOAD)

    jobs = LeverAdapter("globex", transport=httpx.MockTransport(handler), sleep=lambda s: None).fetch()
    assert len(jobs) == 1 and calls["n"] == 2


def test_adapter_non_json_gives_up_with_error():
    t = transport_for({"https://api.lever.co/v0/postings/globex": (200, "<html>oops</html>", "text/html")})
    with pytest.raises(SourceError, match="non-JSON"):
        LeverAdapter("globex", transport=t, sleep=lambda s: None).fetch()


# ---------------------------------------------------------------- matching

def test_fingerprint_dedupes_across_sources():
    assert job_fingerprint("Globex Inc.", "Senior Backend Engineer", "New York, NY") == \
        job_fingerprint("globex", "senior backend engineer", "New York")


def test_find_skills_handles_symbols():
    assert {"c++", "node.js", "postgresql"} <= set(find_skills("We use C++, Node.js and Postgres"))


def test_years_of_experience_non_overlapping():
    yoe = years_of_experience([{"start": "Jan 2018", "end": "Jan 2020"}, {"start": "Jan 2019", "end": "Jan 2021"}])
    assert 2.9 < yoe < 3.1


def test_match_score_is_transparent_and_bounded():
    a = assess(job_obj(), profile_obj())
    assert 0 <= a["score"] <= 100
    comps = {k: v for k, v in a["breakdown"].items() if not k.startswith("_")}
    assert set(comps) == {"keywords", "title", "experience", "education", "soft_skills"}
    assert set(a["breakdown"]["_preferences"]) == {"location", "compensation", "seniority"}
    total_points = sum(b["points"] for b in comps.values())
    assert abs(total_points - a["score"]) <= 1
    assert "kubernetes" in a["missing_skills"] and "python" in a["matched_skills"]
    assert a["recommendation"] in ("apply", "review", "skip")


def test_weights_change_score():
    zero = {"keywords": 0, "title": 0, "experience": 0, "education": 0, "soft_skills": 0}
    p_skills = profile_obj(match_weights={**zero, "keywords": 100})
    p_title = profile_obj(match_weights={**zero, "title": 100})
    j = job_obj()
    assert assess(j, p_title, "Senior Backend Engineer at Acme")["score"] == 100
    assert assess(j, p_skills)["score"] < 100


def test_sponsorship_conflict_flag_caps_recommendation():
    j = job_obj(description_text="Python FastAPI PostgreSQL AWS Docker Redis. We are unable to sponsor visas.")
    a = assess(j, profile_obj(work_authorization={"requires_sponsorship": True}))
    assert any(f.startswith("Work authorization") for f in a["flags"])
    assert a["recommendation"] != "apply"
    a2 = assess(j, profile_obj(work_authorization={"requires_sponsorship": None}))
    assert any("Set your sponsorship" in f for f in a2["flags"])


# ---------------------------------------------------------------- tailoring

def test_fact_guard():
    ev = "python fastapi redis"
    assert fact_guard("Cut latency by 40%", "Reduced latency 40%", ev) == []
    assert fact_guard("Cut latency", "Cut latency by 60%", ev)
    assert fact_guard("Built APIs", "Built APIs with Kubernetes", ev)


def test_tailored_resume_preserves_facts_and_master():
    p = profile_obj()
    before = json.dumps(p.experience, sort_keys=True)
    content, flags, gen = tailor_resume(p, job_obj())
    assert gen == "deterministic"
    assert json.dumps(p.experience, sort_keys=True) == before  # master never mutated
    for orig, new in zip(p.experience, content["experience"]):
        for k in ("company", "title", "start", "end"):
            assert orig[k] == new[k]
        assert sorted(b["original"] for b in new["bullets"]) == sorted(orig["bullets"])
        for b in new["bullets"]:
            assert fact_guard(b["original"], b["text"], candidate_evidence_text(p)) == []
    assert "kubernetes" in content["keywords"]["missing"]
    assert "Kubernetes" not in content["skills"]
    assert any(f["path"] == "keywords" for f in flags)
    # opener polish
    texts = [b["text"] for b in content["experience"][0]["bullets"]]
    assert any(t.startswith("Owned the payments API") for t in texts)


def test_llm_rewrite_with_invented_metric_is_rejected(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm.settings, "openai_api_key", "sk-test")

    def fake_complete(task, payload, schema, **kw):
        assert "<untrusted_job_description>" in payload  # job text is fenced as data
        return {"bullets": [{"id": "e0b0", "text": "Led the payments API serving 9M requests/day"},
                            {"id": "e0b1", "text": "Reduced p95 latency by 40% by introducing Redis caching"}]}

    monkeypatch.setattr(llm, "complete_json", fake_complete)
    content, flags, gen = tailor_resume(profile_obj(), job_obj())
    assert gen.startswith("llm:")
    bullets = {b["id"]: b for b in content["experience"][0]["bullets"]}
    assert bullets["e0b0"]["flagged"] and "9M" not in bullets["e0b0"]["text"]
    assert bullets["e0b1"]["text"].startswith("Reduced p95 latency by 40%")
    assert any("rejected" in f["message"] for f in flags)


def test_locked_fields_cannot_be_edited():
    content, _, _ = tailor_resume(profile_obj(), job_obj())
    edited = json.loads(json.dumps(content))
    edited["experience"][0]["title"] = "CTO"
    assert validate_resume_edit(content, edited)
    edited = json.loads(json.dumps(content))
    edited["experience"][0]["bullets"][0]["text"] = "Rewritten by me"
    assert validate_resume_edit(content, edited) == []


def test_cover_letter_requires_user_motivation():
    a = assess(job_obj(), profile_obj())
    content, flags, _ = cover_letter(profile_obj(), job_obj(), a)
    assert "Globex" in content["body"]
    assert unresolved_placeholders(content)
