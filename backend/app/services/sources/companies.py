"""Company career-portal adapters (public job-board feeds, no credentials).

Each takes the company's board identifier (the slug in its careers URL):
  Ashby           https://jobs.ashbyhq.com/<name>
  SmartRecruiters https://careers.smartrecruiters.com/<CompanyIdentifier>
  Workable        https://apply.workable.com/<account>
  Recruitee       https://<company>.recruitee.com
Greenhouse and Lever live in their own modules.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..textutil import strip_html
from .base import JobSourceAdapter, NormalizedJob, SourceError, infer_remote_type


def _dt(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


class AshbyAdapter(JobSourceAdapter):
    kind = "ashby"
    docs_url = "https://developers.ashbyhq.com/docs/public-job-posting-api"

    def fetch(self) -> list[NormalizedJob]:
        data = self._get_json(f"https://api.ashbyhq.com/posting-api/job-board/{self.identifier}",
                              params={"includeCompensation": "true"})
        if not isinstance(data, dict) or "jobs" not in data:
            raise SourceError(f"ashby: board '{self.identifier}' not found.", status=404)
        company = self.company_name()
        return [n for n in (self.normalize(j, company) for j in data.get("jobs") or [] if j.get("isListed", True)) if n]

    @staticmethod
    def normalize(j: dict, company: str) -> Optional[NormalizedJob]:
        if not j.get("title") or not (j.get("id") or j.get("jobUrl")):
            return None
        wt = (j.get("workplaceType") or "").lower()
        remote = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(wt) or ("remote" if j.get("isRemote") else infer_remote_type(j.get("location", "")))
        comp = j.get("compensation") or {}
        smin = smax = None
        cur = ""
        for t in comp.get("summaryComponents") or []:
            if t.get("compensationType") == "Salary" and (t.get("interval") or "").lower().startswith("1 year"):
                smin, smax, cur = t.get("minValue"), t.get("maxValue"), t.get("currencyCode") or ""
        return NormalizedJob(
            external_id=str(j.get("id") or j.get("jobUrl")), title=j["title"].strip(), company=company,
            location=j.get("location", "") or "", remote_type=remote, employment_type=j.get("employmentType", "") or "",
            department=" · ".join(x for x in [j.get("department"), j.get("team")] if x),
            description_text=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
            salary_min=smin, salary_max=smax, salary_currency=cur, salary_interval="per-year-salary" if smin else "",
            posted_at=_dt(j.get("publishedAt")), url=j.get("jobUrl", "") or "", apply_url=j.get("applyUrl", "") or j.get("jobUrl", ""))


class SmartRecruitersAdapter(JobSourceAdapter):
    kind = "smartrecruiters"
    docs_url = "https://developers.smartrecruiters.com/docs/posting-api"
    detail_limit = 40  # descriptions need one call per posting; only fetched for jobs that pass the title filter

    def __init__(self, identifier: str, **kw):
        super().__init__(identifier, **kw)
        self.title_filter = None  # set by discovery: callable(title) -> bool

    def fetch(self) -> list[NormalizedJob]:
        base = f"https://api.smartrecruiters.com/v1/companies/{self.identifier}/postings"
        out, offset = [], 0
        while offset < 500:
            data = self._get_json(base, params={"limit": 100, "offset": offset})
            items = (data or {}).get("content", [])
            out.extend(items)
            if len(items) < 100:
                break
            offset += 100
        if not out and not (data or {}).get("totalFound"):
            # an unknown company id returns an empty list rather than 404
            pass
        company = (out[0].get("company") or {}).get("name") if out else self.company_name()
        jobs = []
        details = 0
        for p in out:
            title = p.get("name", "")
            desc = ""
            if self.title_filter is None or self.title_filter(title):
                if details < self.detail_limit:
                    try:
                        d = self._get_json(f"{base}/{p['id']}", max_attempts=1)
                        secs = ((d or {}).get("jobAd") or {}).get("sections") or {}
                        desc = "\n\n".join(strip_html((secs.get(k) or {}).get("text", "")) for k in
                                           ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
                        details += 1
                    except SourceError:
                        pass
            n = self.normalize(p, company or self.company_name(), desc)
            if n:
                jobs.append(n)
        return jobs

    def normalize(self, p: dict, company: str, desc: str) -> Optional[NormalizedJob]:
        if not p.get("id") or not p.get("name"):
            return None
        loc = p.get("location") or {}
        where = ", ".join(x for x in [loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()] if x)
        url = f"https://jobs.smartrecruiters.com/{self.identifier}/{p['id']}"
        return NormalizedJob(
            external_id=str(p["id"]), title=p["name"].strip(), company=company, location=where,
            remote_type="remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else infer_remote_type(where)),
            employment_type=(p.get("typeOfEmployment") or {}).get("label", "") or "",
            department=(p.get("department") or {}).get("label", "") or "", description_text=desc,
            posted_at=_dt(p.get("releasedDate")), url=url, apply_url=url)


class WorkableAdapter(JobSourceAdapter):
    kind = "workable"
    docs_url = "https://help.workable.com/hc/en-us/articles/115012771647"

    def fetch(self) -> list[NormalizedJob]:
        data = self._get_json(f"https://apply.workable.com/api/v1/widget/accounts/{self.identifier}", params={"details": "true"})
        if not isinstance(data, dict) or "jobs" not in data:
            raise SourceError(f"workable: account '{self.identifier}' not found.", status=404)
        company = data.get("name") or self.company_name()
        return [n for n in (self.normalize(j, company) for j in data.get("jobs") or []) if n]

    @staticmethod
    def normalize(j: dict, company: str) -> Optional[NormalizedJob]:
        jid = j.get("shortcode") or j.get("id") or j.get("code")
        if not jid or not j.get("title"):
            return None
        locs = j.get("locations") or ([j["location"]] if isinstance(j.get("location"), dict) else [])
        parts = []
        for l in locs[:3]:
            parts.append(", ".join(x for x in [l.get("city"), l.get("region") or l.get("state_code"), l.get("country") or l.get("country_name")] if x))
        where = " / ".join(p for p in parts if p) or ", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x)
        tele = j.get("telecommuting") or any(l.get("telecommuting") for l in locs)
        wp = next((l.get("workplace_type") for l in locs if l.get("workplace_type")), "")
        desc = strip_html(j.get("full_description") or j.get("description") or "")
        return NormalizedJob(
            external_id=str(jid), title=j["title"].strip(), company=company, location=where,
            remote_type="remote" if tele or wp == "remote" else ("hybrid" if wp == "hybrid" else infer_remote_type(where)),
            employment_type=j.get("employment_type", "") or "", department=j.get("department", "") or "",
            description_text=desc, posted_at=_dt(j.get("published_on") or j.get("created_at")),
            url=j.get("url") or j.get("shortlink") or "", apply_url=j.get("application_url") or j.get("url") or "")


class RecruiteeAdapter(JobSourceAdapter):
    kind = "recruitee"
    docs_url = "https://docs.recruitee.com/reference/offers"

    def fetch(self) -> list[NormalizedJob]:
        data = self._get_json(f"https://{self.identifier}.recruitee.com/api/offers/")
        if not isinstance(data, dict) or "offers" not in data:
            raise SourceError(f"recruitee: careers site '{self.identifier}' not found.", status=404)
        return [n for n in (self.normalize(o, self.company_name()) for o in data.get("offers") or []) if n]

    @staticmethod
    def normalize(o: dict, company: str) -> Optional[NormalizedJob]:
        if not o.get("id") or not o.get("title"):
            return None
        where = o.get("location") or ", ".join(x for x in [o.get("city"), o.get("country")] if x)
        return NormalizedJob(
            external_id=str(o["id"]), title=o["title"].strip(), company=o.get("company_name") or company, location=where or "",
            remote_type="remote" if o.get("remote") else ("hybrid" if o.get("hybrid") else infer_remote_type(where or "")),
            employment_type=o.get("employment_type_code", "") or "", department=o.get("department", "") or "",
            description_text=strip_html((o.get("description") or "") + "\n" + (o.get("requirements") or "")),
            posted_at=_dt(o.get("published_at") or o.get("created_at")), url=o.get("careers_url", "") or "",
            apply_url=o.get("careers_apply_url") or o.get("careers_url") or "")
