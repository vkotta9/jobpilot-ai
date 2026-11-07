"""Role tracks: one resume per kind of role, jobs scored against the track they belong to."""
import io

import pytest

from app.services.roles import TrackView, candidate_tracks, families_for_title, suggest_roles

from .conftest import make_user, setup_profile

SWE_CV = ["Jordan Rivera", "Software Engineer", "jordan@example.com",
          "Experience", "Software Engineer | Acme Corp | Jan 2019 – Present",
          "Built Java Spring Boot microservices and REST API design for distributed systems on Kubernetes.",
          "React and TypeScript front end; system design reviews; unit testing; SQL.",
          "Education", "B.S. Computer Science, State University, 2018",
          "Skills", "Java, Spring, Microservices, REST API, React, TypeScript, SQL, Docker, Kubernetes"]
ML_CV = ["Jordan Rivera", "Machine Learning Engineer", "jordan@example.com",
         "Experience", "Machine Learning Engineer | Acme Corp | Jan 2019 – Present",
         "Trained and deployed deep learning models in PyTorch; fine-tuning LLMs with Hugging Face transformers.",
         "Built RAG pipelines with LangChain and embeddings; MLflow and SageMaker for MLOps.",
         "Education", "M.S. Computer Science, State University, 2018",
         "Skills", "Python, PyTorch, TensorFlow, Machine Learning, Deep Learning, LLM, NLP, MLflow, SageMaker, SQL"]
ML_JD = ("We're hiring a Machine Learning Engineer to train and deploy deep learning models. Required: Python, PyTorch, "
         "machine learning, LLM fine-tuning, MLflow. Nice to have: SageMaker, NLP, embeddings. " * 3)
SWE_JD = ("Backend Software Engineer to build Java Spring microservices and REST APIs for distributed systems. "
          "Required: Java, Spring, microservices, SQL, Kubernetes. Nice to have: React, TypeScript. " * 3)


def _docx(lines) -> bytes:
    import docx

    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _upload(client, h, name, lines) -> int:
    r = client.post("/api/resumes", headers=h, files={"file": (name, _docx(lines), "application/octet-stream")})
    assert r.status_code == 200, r.text
    return r.json()["resume"]["id"]


def _job(client, h, title, jd) -> int:
    r = client.post("/api/jobs/manual", headers=h, json={"title": title, "company": "Globex", "description_text": jd})
    assert r.status_code == 200, r.text
    return r.json()["job"]["id"]


@pytest.mark.parametrize("title,first", [
    ("Software Engineer", "swe"), ("SDE II", "swe"), ("Machine Learning Engineer", "ml"),
    ("Software Engineer, Machine Learning", "ml"), ("Data Scientist, ML", "ds"), ("Research Scientist, AI", "research"),
    ("Senior Data Engineer", "de"), ("Site Reliability Engineer", "devops"), ("Generative AI Engineer", "ml"),
])
def test_job_titles_map_to_role_families(title, first):
    assert families_for_title(title)[0] == first


def test_unrelated_titles_fit_no_family():
    assert families_for_title("Mechanical Engineer") == [] and families_for_title("Sales Manager") == []


def test_suggest_roles_reads_the_resume_focus():
    assert suggest_roles("\n".join(ML_CV))[0]["key"] == "ml"
    assert suggest_roles("\n".join(SWE_CV))[0]["key"] == "swe"
    assert suggest_roles("") == []


def test_candidate_tracks_prefers_the_specific_family():
    swe = TrackView(1, "SWE", "swe", ["Software Engineer"], "")
    ml = TrackView(2, "ML", "ml", ["Machine Learning Engineer"], "")
    assert candidate_tracks([swe, ml], "Software Engineer, Machine Learning") == ([ml], "role")
    assert candidate_tracks([swe, ml], "Backend Software Engineer") == ([swe], "role")
    assert candidate_tracks([swe, ml], "Mechanical Engineer") == ([swe, ml], "closest")


def test_tracks_route_jobs_to_the_right_resume(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    swe_id = _upload(client, h, "swe.docx", SWE_CV)
    ml_id = _upload(client, h, "ml.docx", ML_CV)
    j_ml = _job(client, h, "Machine Learning Engineer", ML_JD)
    j_swe = _job(client, h, "Backend Software Engineer", SWE_JD)

    fams = client.get("/api/roles", headers=h).json()
    assert {"swe", "ml", "ds"} <= {f["key"] for f in fams}
    t_swe = client.post("/api/tracks", headers=h, json={"family": "swe", "resume_id": swe_id}).json()
    t_ml = client.post("/api/tracks", headers=h, json={"family": "ml", "resume_id": ml_id,
                                                       "target_titles": ["Machine Learning Engineer", "AI Engineer"]}).json()
    assert t_swe["name"] == "Software Engineer / SDE" and t_swe["target_titles"][0] == "Software Engineer"

    listing = client.get("/api/tracks", headers=h).json()
    assert [t["name"] for t in listing["tracks"]] == ["Software Engineer / SDE", "Machine Learning / AI Engineer"]
    by_file = {r["filename"]: r for r in listing["resumes"]}
    assert by_file["ml.docx"]["suggested_roles"][0]["key"] == "ml" and by_file["ml.docx"]["used_by"]

    d_ml = client.get(f"/api/jobs/{j_ml}", headers=h).json()
    assert d_ml["match"]["track_id"] == t_ml["id"] and d_ml["resume_track"]["resume"] == "ml.docx"
    assert d_ml["match"]["breakdown"]["_track"]["reason"] == "role"
    d_swe = client.get(f"/api/jobs/{j_swe}", headers=h).json()
    assert d_swe["match"]["track_id"] == t_swe["id"]

    ml_jobs = client.get(f"/api/tracks/{t_ml['id']}/jobs", headers=h).json()
    assert [j["id"] for j in ml_jobs["items"]] == [j_ml]
    lst = client.get(f"/api/jobs?track={t_ml['id']}&view=all&qualified_only=false", headers=h).json()
    assert [j["id"] for j in lst["items"]] == [j_ml]

    # the ML resume scores the ML job better than the SWE resume would
    client.post(f"/api/jobs/{j_ml}/track", headers=h, json={"track_id": t_swe["id"]})
    forced = client.get(f"/api/jobs/{j_ml}", headers=h).json()
    assert forced["match"]["track_id"] == t_swe["id"] and forced["resume_track"]["chosen"]
    assert forced["match"]["score"] < d_ml["match"]["score"]
    back = client.post(f"/api/jobs/{j_ml}/track", headers=h, json={"track_id": None}).json()
    assert back["track_id"] == t_ml["id"]


def test_tailoring_uses_the_track_resume(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    swe_id = _upload(client, h, "swe.docx", SWE_CV)  # first upload = primary
    ml_id = _upload(client, h, "ml.docx", ML_CV)
    client.post("/api/tracks", headers=h, json={"family": "swe", "resume_id": swe_id})
    client.post("/api/tracks", headers=h, json={"family": "ml", "resume_id": ml_id})
    j = _job(client, h, "Machine Learning Engineer", ML_JD)
    client.get(f"/api/jobs/{j}", headers=h)
    doc = client.post(f"/api/jobs/{j}/resume/tailor", headers=h)
    assert doc.status_code == 200, doc.text
    assert doc.json()["content"].get("resume_id") == ml_id


def test_track_limits_and_validation(client):
    h, _ = make_user(client)
    setup_profile(client, h)
    for fam in ("swe", "ml", "ds"):
        assert client.post("/api/tracks", headers=h, json={"family": fam}).status_code == 200
    r = client.post("/api/tracks", headers=h, json={"family": "devops"})
    assert r.status_code == 400 and "up to 3" in r.json()["detail"]
    assert client.post("/api/tracks", headers=h, json={"family": "astrology"}).status_code == 422
    other, _ = make_user(client)
    tid = client.get("/api/tracks", headers=h).json()["tracks"][0]["id"]
    assert client.delete(f"/api/tracks/{tid}", headers=other).status_code == 404
    assert client.delete(f"/api/tracks/{tid}", headers=h).status_code == 200
    custom = client.post("/api/tracks", headers=h, json={"family": "custom", "name": "Solutions Architect"}).json()
    assert custom["target_titles"] == ["Solutions Architect"]


def test_search_uses_every_tracks_titles(client):
    from app.db import SessionLocal
    from app.models import User
    from app.services.discovery import search_context

    h, email = make_user(client)
    setup_profile(client, h)
    client.post("/api/tracks", headers=h, json={"family": "swe"})
    client.post("/api/tracks", headers=h, json={"family": "ml"})
    with SessionLocal() as db:
        ctx = search_context(db, db.query(User).filter_by(email=email).one().id)
    assert ctx["queries"][:2] == ["Software Engineer", "Machine Learning Engineer"]
    assert "AI Engineer" in ctx["title_terms"] and "Software Development Engineer" in ctx["title_terms"]
