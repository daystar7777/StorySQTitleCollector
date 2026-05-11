#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Tuple


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


def build_submission(
    lease_id: str,
    worker_id: str,
    submission_id: str,
    mode: str,
    connector_id: str,
    model_vendor: str,
    model_id: str,
    harness: str,
) -> Dict[str, Any]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    bundle_id = f"bundle_{submission_id}"
    bundle = candidate_bundle(lease_id, worker_id, bundle_id, model_id)
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


def submit_to_target(target: str, submission: Dict[str, Any], manifest: Dict[str, Any], lease_req: Dict[str, Any], pb2: Any, pb2_grpc: Any, grpc: Any) -> Dict[str, str]:
    channel = grpc.insecure_channel(target)
    try:
        registry = pb2_grpc.WorkerRegistryStub(channel)
        allocator = pb2_grpc.TitleWorkAllocatorStub(channel)
        intake = pb2_grpc.CandidateIntakeStub(channel)

        registration = registry.RegisterWorker(pb2.RegisterWorkerIn(manifest_json=canonical_json(manifest)))
        if registration.state != "active":
            return {"registered": registration.state, "reason": registration.reason}
        heartbeat = registry.Heartbeat(pb2.WorkerHeartbeatIn(worker_id=registration.worker_id))
        lease = allocator.LeaseTitleSlice(
            pb2.LeaseTitleSliceIn(worker_id=registration.worker_id, request_json=canonical_json(lease_req))
        )
        submission["payload"]["lease_id"] = lease.lease_id
        submission["payload"]["source_worker_id"] = registration.worker_id
        ingest = intake.SubmitConnectorSubmission(
            pb2.SubmitConnectorSubmissionIn(connector_submission_json=canonical_json(submission))
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
        )
        return submit_to_target(
            f"127.0.0.1:{port}",
            submission,
            manifest,
            lease_request(),
            pb2,
            pb2_grpc,
            grpc,
        )
    finally:
        server.stop(0)
        dashboard.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="StorySQ TitleCollector M1 uploader/connector")
    parser.add_argument("--dashboard-root", default=str(DEFAULT_DASHBOARD))
    parser.add_argument("--target", help=f"Dashboard gRPC target. Defaults to {TARGET_ENV_KEY} from .env or environment.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Local env file for Dashboard target configuration")
    parser.add_argument("--self-test", action="store_true", help="Start an in-process Dashboard gRPC server and run one attach")
    parser.add_argument("--mode", choices=["fixture", "production"], default="production")
    parser.add_argument("--worker-id", default="storysq_titlecollector_m1")
    parser.add_argument("--submission-id", default="sub_storysq_titlecollector_m1")
    parser.add_argument("--connector-id", default="storysq.titlecollector.uploader")
    parser.add_argument("--model-vendor", default="openai")
    parser.add_argument("--model-id", default="gpt-5-codex")
    parser.add_argument("--harness", default="codex-cli")
    parser.add_argument("--print-envelope", action="store_true")
    args = parser.parse_args()

    if args.print_envelope:
        print(json.dumps(build_submission("lease_pending", args.worker_id, args.submission_id, args.mode, args.connector_id, args.model_vendor, args.model_id, args.harness), indent=2, sort_keys=True))
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
    manifest = worker_manifest(args.worker_id, args.model_vendor, args.model_id, args.harness)
    submission = build_submission("lease_pending", args.worker_id, args.submission_id, args.mode, args.connector_id, args.model_vendor, args.model_id, args.harness)
    print(json.dumps(submit_to_target(args.target, submission, manifest, lease_request(), pb2, pb2_grpc, grpc), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
