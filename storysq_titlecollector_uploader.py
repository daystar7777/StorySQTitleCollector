#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
PROMPT_PATH = ROOT / "prompts" / "titlecollector.m1.md"
DEFAULT_DASHBOARD = ROOT.parent / "StorySQ_Content" / "Content_Dashboard"
DEFAULT_ENV_FILE = ROOT / ".env"
TARGET_ENV_KEY = "STORYSQ_DASHBOARD_TARGET"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def protocol_manifest_hash() -> str:
    manifest = {
        "pack_id": "titlecollector.m1",
        "pack_version": "1.0.0",
        "schema_id": "dashboard.candidate_bundle.v1",
        "protocol_name": "TitleCollector Candidate Bundle — M1",
        "min_connector_version": "1.0.0",
    }
    return sha256_text(json.dumps(manifest, sort_keys=True))


def worker_manifest(worker_id: str, model_vendor: str, model_id: str, harness: str) -> Dict[str, Any]:
    return {
        "worker_id": worker_id,
        "worker_kind": "titlecollector",
        "vendor": model_vendor,
        "model_id": model_id,
        "harness": harness,
        "capabilities": ["title.discovery", "title.enrichment", "emit:candidate"],
        "max_concurrent_jobs": 1,
        "public_key": "ed25519:storysq-titlecollector-m1",
        "registration_manifest_hash": sha256_text(f"{worker_id}:{model_vendor}:{model_id}:{harness}")[:32],
    }


def lease_request() -> Dict[str, Any]:
    return {
        "language_bucket": "ISO639",
        "primary_language_tag": "en",
        "era": "modern",
        "tier1_genres": ["poetry"],
        "source_ids": ["src_tier1_titles"],
        "lease_until": "2999-01-01T00:00:00Z",
    }


def evidence_claim(agent: str, claim_id: str = "claim_m1_publication_year") -> Dict[str, Any]:
    return {
        "claim_id": claim_id,
        "about_path": "$.candidates[0].date_handling.date_raw",
        "asserted_value": "1900",
        "confidence": 0.95,
        "agent": agent,
        "tier": "T1",
        "source_uris": ["https://example.invalid/storysq-titlecollector-m1/catalog"],
        "prompt_policy_id": "titlecollector.m1.prompt.v1",
        "extraction_policy_id": "titlecollector.m1.connector.v1",
        "observed_at": "2026-05-10T00:00:00Z",
        "signature": "sig-storysq-titlecollector-m1",
    }


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{sha256_text(value)[:12]}"


def year_from_value(value: Any) -> Optional[int]:
    if value is None:
        return None
    match = re.search(r"\b(\d{4})\b", str(value))
    if not match:
        return None
    return int(match.group(1))


def candidate_from_seed(seed: Dict[str, Any], index: int, agent: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    title = str(seed.get("title_raw") or seed.get("title") or "").strip()
    if not title:
        raise ValueError(f"candidate seed {index} missing title")
    author = str(seed.get("author_raw") or seed.get("author") or "").strip()
    source_uri = str(seed.get("source_uri") or seed.get("url") or "").strip()
    language = str(seed.get("language") or "en").strip() or "en"
    genre = str(seed.get("genre") or "fiction").strip() or "fiction"
    raw_date = str(seed.get("date_raw") or seed.get("issued") or "").strip()
    date_kind = str(seed.get("date_kind") or ("catalog_issued" if seed.get("issued") else "unknown"))
    year = year_from_value(raw_date)
    temp_id = str(seed.get("temp_id") or stable_id("cand", f"{title}:{author}:{source_uri}"))
    claim_id = str(seed.get("claim_id") or stable_id("claim", f"{temp_id}:{source_uri}:{title}"))
    source_uris = [source_uri] if source_uri else []
    claim = {
        "claim_id": claim_id,
        "about_path": f"$.candidates[{index}].putative_work_key.title_raw",
        "asserted_value": title,
        "confidence": float(seed.get("confidence", 0.9)),
        "agent": agent,
        "tier": str(seed.get("tier") or "T1"),
        "source_uris": source_uris,
        "prompt_policy_id": "titlecollector.m1.prompt.v1",
        "extraction_policy_id": "titlecollector.m1.connector.v1",
        "observed_at": str(seed.get("observed_at") or "2026-05-12T00:00:00Z"),
        "signature": "sig-storysq-titlecollector-m1",
    }
    era_range = {
        "start": year,
        "end": year,
        "source": str(seed.get("date_source") or "Project Gutenberg catalog metadata"),
        "era": str(seed.get("era") or "modern"),
    }
    return (
        {
            "temp_id": temp_id,
            "putative_work_key": {
                "title_normalized": normalize_text(title),
                "title_raw": title,
                "author_normalized": normalize_text(author) if author else "",
                "author_raw": author,
            },
            "language_assignment": {
                "primary_bucket": "ISO639",
                "primary_language_tag": language,
                "minority_language_tag": None,
                "script_tags": [str(seed.get("script") or "Latn")],
                "secondary_languages": seed.get("secondary_languages", []),
                "modern_descendants": [],
                "language_layers": [],
                "cross_search_edges": [],
            },
            "genres": [genre],
            "attribution": {
                "attribution_type": "single_author" if author else "unknown",
                "contributor_refs": [],
                "attribution_evidence_claim_ids": [claim_id],
            },
            "sensitivity_flags": seed.get("sensitivity_flags", []),
            "approximate_era_range": era_range,
            "date_handling": {
                "date_raw": raw_date,
                "date_normalized_range": {"start": year, "end": year},
                "date_estimate_source": era_range["source"],
            },
            "edition": {
                "requested_edition_id": seed.get("requested_edition_id"),
                "edition_unbound": bool(seed.get("edition_unbound", False)),
                "edition_resolution_status": str(seed.get("edition_resolution_status") or "unresolved"),
                "edition_cues": seed.get("edition_cues", []),
            },
            "collector_hints": {
                "suspected_source_id": str(seed.get("source_id") or "project_gutenberg"),
                "suspected_url_or_catalog_ref": source_uri,
                "fetch_driver_hint": None,
                "classification_codes": {"gutenberg_ebook_id": str(seed.get("gutenberg_ebook_id") or "")},
            },
            "pd_risk_signals": {
                "author_death_year_claims": [],
                "publication_year_claims": [claim_id] if raw_date and date_kind == "publication" else [],
                "translator_editor_claims": [],
                "anonymous_or_pseudonymous_signal": False,
                "jurisdiction_relevance_claims": [],
                "known_estate_or_rights_warning": False,
                "validator_attention_level": "normal",
            },
            "canonical_priority_claim": {
                "evidence_claim_id": claim_id,
                "asserted_value": str(seed.get("canonical_priority") or "normal"),
                "confidence": float(seed.get("priority_confidence", 0.85)),
            },
            "absence_records": [],
        },
        claim,
    )


def load_candidate_seeds(path: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("candidates")
    if not isinstance(value, list):
        raise ValueError("candidates JSON must be a list or an object with a candidates list")
    return value


def candidate_bundle(lease_id: str, worker_id: str, bundle_id: str, agent: str) -> Dict[str, Any]:
    claim = evidence_claim(agent)
    return {
        "bundle_id": bundle_id,
        "schema_version": "dashboard.candidate_bundle.v1",
        "source_worker_id": worker_id,
        "lease_id": lease_id,
        "origin_discovery_run_id": "run_storysq_titlecollector_m1",
        "created_at": "2026-05-10T00:00:00Z",
        "submitted_at": "2026-05-10T00:00:01Z",
        "candidates": [
            {
                "temp_id": "cand_m1_1",
                "putative_work_key": {
                    "title_normalized": "storysq m1 fixture poem",
                    "title_raw": "StorySQ M1 Fixture Poem",
                    "author_normalized": "storysq fixture author",
                    "author_raw": "StorySQ Fixture Author",
                },
                "language_assignment": {
                    "primary_bucket": "ISO639",
                    "primary_language_tag": "en",
                    "minority_language_tag": None,
                    "script_tags": ["Latn"],
                    "secondary_languages": [],
                    "modern_descendants": [],
                    "language_layers": [],
                    "cross_search_edges": [],
                },
                "genres": ["poetry"],
                "attribution": {
                    "attribution_type": "single_author",
                    "contributor_refs": [],
                    "attribution_evidence_claim_ids": [claim["claim_id"]],
                },
                "sensitivity_flags": [],
                "approximate_era_range": {"start": 1900, "end": 1900, "source": "M1 connector seed", "era": "modern"},
                "date_handling": {
                    "date_raw": "1900",
                    "date_normalized_range": {"start": 1900, "end": 1900},
                    "date_estimate_source": "M1 connector seed",
                },
                "edition": {
                    "requested_edition_id": None,
                    "edition_unbound": False,
                    "edition_resolution_status": "resolved",
                    "edition_cues": [],
                },
                "collector_hints": {
                    "suspected_source_id": "src_tier1_titles",
                    "suspected_url_or_catalog_ref": "https://example.invalid/storysq-titlecollector-m1/catalog",
                    "fetch_driver_hint": None,
                    "classification_codes": {},
                },
                "pd_risk_signals": {
                    "author_death_year_claims": [],
                    "publication_year_claims": [claim["claim_id"]],
                    "translator_editor_claims": [],
                    "anonymous_or_pseudonymous_signal": False,
                    "jurisdiction_relevance_claims": [],
                    "known_estate_or_rights_warning": False,
                    "validator_attention_level": "normal",
                },
                "canonical_priority_claim": {
                    "evidence_claim_id": claim["claim_id"],
                    "asserted_value": "normal",
                    "confidence": 0.9,
                },
                "absence_records": [],
            }
        ],
        "relation_hypotheses": [],
        "evidence_claims": [claim],
        "risk_signals": [],
        "coverage_signals": [],
        "idempotency_key": f"candidate_bundle:{bundle_id}:submitted",
    }


def candidate_bundle_from_seeds(
    lease_id: str,
    worker_id: str,
    bundle_id: str,
    agent: str,
    seeds: List[Dict[str, Any]],
) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    claims: List[Dict[str, Any]] = []
    for index, seed in enumerate(seeds):
        candidate, claim = candidate_from_seed(seed, index, agent)
        candidates.append(candidate)
        claims.append(claim)
    return {
        "bundle_id": bundle_id,
        "schema_version": "dashboard.candidate_bundle.v1",
        "source_worker_id": worker_id,
        "lease_id": lease_id,
        "origin_discovery_run_id": "run_storysq_titlecollector_m1",
        "created_at": "2026-05-12T00:00:00Z",
        "submitted_at": "2026-05-12T00:00:01Z",
        "candidates": candidates,
        "relation_hypotheses": [],
        "evidence_claims": claims,
        "risk_signals": [],
        "coverage_signals": [],
        "idempotency_key": f"candidate_bundle:{bundle_id}:submitted",
    }


def build_submission(
    lease_id: str,
    worker_id: str,
    submission_id: str,
    mode: str,
    connector_id: str,
    model_vendor: str,
    model_id: str,
    harness: str,
    candidate_seeds: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    bundle_id = f"bundle_{submission_id}"
    if candidate_seeds is None:
        bundle = candidate_bundle(lease_id, worker_id, bundle_id, model_id)
    else:
        bundle = candidate_bundle_from_seeds(lease_id, worker_id, bundle_id, model_id, candidate_seeds)
    output_markdown = "# CandidateBundleSubmitted\n\n```json\n" + json.dumps(bundle, indent=2, sort_keys=True) + "\n```\n"
    return {
        "submission_id": submission_id,
        "pack_id": "titlecollector.m1",
        "pack_version": "1.0.0",
        "schema_id": "dashboard.candidate_bundle.v1",
        "mode": mode,
        "connector": {
            "connector_id": connector_id,
            "connector_version": "1.0.0",
            "protocol_pack_manifest_hash": protocol_manifest_hash(),
            "harness": harness,
            "model_vendor": model_vendor,
            "model_id": model_id,
            "prompt_template_version": "1.0.0",
            "prompt_hash": sha256_text(prompt),
            "output_markdown_hash": sha256_text(output_markdown),
        },
        "payload": bundle,
    }


def import_dashboard(dashboard_root: Path) -> Tuple[Any, Any, Any]:
    dashboard_root = dashboard_root.resolve()
    generated = dashboard_root / "dashboard_m1" / "generated"
    for path in (dashboard_root, generated):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import grpc  # type: ignore
    from dashboard_m1.services import DashboardM1  # type: ignore
    from dashboard_m1.grpc_server import create_server  # type: ignore
    import dashboard_m1_pb2 as pb2  # type: ignore
    import dashboard_m1_pb2_grpc as pb2_grpc  # type: ignore

    return grpc, (DashboardM1, create_server), (pb2, pb2_grpc)


def normalize_target(target: str) -> Tuple[str, bool]:
    if target.startswith("grpcs://"):
        return target.removeprefix("grpcs://"), True
    if target.startswith("grpc://"):
        return target.removeprefix("grpc://"), False
    return target, False


def submit_to_target(
    target: str,
    submission: Dict[str, Any],
    manifest: Dict[str, Any],
    lease_req: Dict[str, Any],
    pb2: Any,
    pb2_grpc: Any,
    grpc: Any,
    use_tls: bool = False,
    rpc_timeout: float = 10.0,
) -> Dict[str, str]:
    target, scheme_tls = normalize_target(target)
    if use_tls or scheme_tls:
        channel = grpc.secure_channel(target, grpc.ssl_channel_credentials())
    else:
        channel = grpc.insecure_channel(target)
    try:
        try:
            grpc.channel_ready_future(channel).result(timeout=rpc_timeout)
            registry = pb2_grpc.WorkerRegistryStub(channel)
            allocator = pb2_grpc.TitleWorkAllocatorStub(channel)
            intake = pb2_grpc.CandidateIntakeStub(channel)

            registration = registry.RegisterWorker(pb2.RegisterWorkerIn(manifest_json=canonical_json(manifest)), timeout=rpc_timeout)
            if registration.state != "active":
                return {"registered": registration.state, "reason": registration.reason}
            heartbeat = registry.Heartbeat(pb2.WorkerHeartbeatIn(worker_id=registration.worker_id), timeout=rpc_timeout)
            lease = allocator.LeaseTitleSlice(
                pb2.LeaseTitleSliceIn(worker_id=registration.worker_id, request_json=canonical_json(lease_req)),
                timeout=rpc_timeout,
            )
            submission["payload"]["lease_id"] = lease.lease_id
            submission["payload"]["source_worker_id"] = registration.worker_id
            ingest = intake.SubmitConnectorSubmission(
                pb2.SubmitConnectorSubmissionIn(connector_submission_json=canonical_json(submission)),
                timeout=rpc_timeout,
            )
            return {
                "registered": registration.state,
                "heartbeat": heartbeat.state,
                "lease": lease.state,
                "submission": ingest.state,
                "bundle_id": ingest.bundle_id,
                "event_id": ingest.event_id,
                "mode": submission["mode"],
            }
        except grpc.FutureTimeoutError:
            return {"submission": "failed", "reason": "dashboard gRPC channel not ready before timeout"}
        except grpc.RpcError as exc:
            return {
                "submission": "failed",
                "reason": exc.details() or "dashboard gRPC RPC failed",
                "grpc_code": exc.code().name if exc.code() else "UNKNOWN",
            }
    finally:
        channel.close()


def run_self_test(args: argparse.Namespace) -> Dict[str, str]:
    grpc, dashboard_api, pb_api = import_dashboard(Path(args.dashboard_root))
    DashboardM1, create_server = dashboard_api
    pb2, pb2_grpc = pb_api
    dashboard = DashboardM1()
    dashboard.seed_source()
    dashboard.create_dtd_baseline()
    server, port = create_server(dashboard)
    server.start()
    try:
        candidate_seeds = load_candidate_seeds(args.candidates_json)
        manifest = worker_manifest(args.worker_id, args.model_vendor, args.model_id, args.harness)
        submission = build_submission(
            "lease_pending",
            args.worker_id,
            args.submission_id,
            args.mode,
            args.connector_id,
            args.model_vendor,
            args.model_id,
            args.harness,
            candidate_seeds,
        )
        return submit_to_target(
            f"127.0.0.1:{port}",
            submission,
            manifest,
            lease_request(),
            pb2,
            pb2_grpc,
            grpc,
            rpc_timeout=args.rpc_timeout,
        )
    finally:
        server.stop(0)
        dashboard.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="StorySQ TitleCollector M1 uploader/connector")
    parser.add_argument("--dashboard-root", default=str(DEFAULT_DASHBOARD))
    parser.add_argument("--target", help=f"Dashboard gRPC target. Defaults to {TARGET_ENV_KEY} from .env or environment.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Local env file for Dashboard target configuration")
    parser.add_argument("--tls", action="store_true", help="Use TLS for the Dashboard gRPC channel")
    parser.add_argument("--rpc-timeout", type=float, default=10.0, help="Per-RPC timeout in seconds")
    parser.add_argument("--self-test", action="store_true", help="Start an in-process Dashboard gRPC server and run one attach")
    parser.add_argument("--mode", choices=["fixture", "production"], default="production")
    parser.add_argument("--worker-id", default="storysq_titlecollector_m1")
    parser.add_argument("--submission-id", default="sub_storysq_titlecollector_m1")
    parser.add_argument("--connector-id", default="storysq.titlecollector.uploader")
    parser.add_argument("--candidates-json", help="Optional candidate seed JSON file for real titlecollector-style runs")
    parser.add_argument("--model-vendor", default="openai")
    parser.add_argument("--model-id", default="gpt-5-codex")
    parser.add_argument("--harness", default="codex-cli")
    parser.add_argument("--print-envelope", action="store_true")
    args = parser.parse_args()

    if args.print_envelope:
        candidate_seeds = load_candidate_seeds(args.candidates_json)
        print(json.dumps(build_submission("lease_pending", args.worker_id, args.submission_id, args.mode, args.connector_id, args.model_vendor, args.model_id, args.harness, candidate_seeds), indent=2, sort_keys=True))
        return 0

    if args.self_test:
        print(json.dumps(run_self_test(args), indent=2, sort_keys=True))
        return 0

    if not args.target:
        env_values = load_env_file(Path(args.env_file))
        args.target = os.environ.get(TARGET_ENV_KEY) or env_values.get(TARGET_ENV_KEY)
    if not args.target:
        parser.error(f"--target or {TARGET_ENV_KEY} in .env is required unless --self-test or --print-envelope is used")

    grpc, _, pb_api = import_dashboard(Path(args.dashboard_root))
    pb2, pb2_grpc = pb_api
    candidate_seeds = load_candidate_seeds(args.candidates_json)
    manifest = worker_manifest(args.worker_id, args.model_vendor, args.model_id, args.harness)
    submission = build_submission("lease_pending", args.worker_id, args.submission_id, args.mode, args.connector_id, args.model_vendor, args.model_id, args.harness, candidate_seeds)
    print(json.dumps(submit_to_target(args.target, submission, manifest, lease_request(), pb2, pb2_grpc, grpc, use_tls=args.tls, rpc_timeout=args.rpc_timeout), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
