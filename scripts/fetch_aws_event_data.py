from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd


DEFAULT_BASE_URL = "https://aws-event-api.bitopro.com"
DEFAULT_OUTPUT_DIR = Path("data/aws_event/raw")


@dataclass(frozen=True)
class EndpointSpec:
    name: str
    order_by: str


ENDPOINT_SPECS: tuple[EndpointSpec, ...] = (
    EndpointSpec("user_info", "user_id"),
    EndpointSpec("train_label", "user_id"),
    EndpointSpec("predict_label", "user_id"),
    EndpointSpec("twd_transfer", "id"),
    EndpointSpec("crypto_transfer", "id"),
    EndpointSpec("usdt_swap", "id"),
    EndpointSpec("usdt_twd_trading", "id"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch official aws-event-api datasets into local parquet files.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--page-size", type=int, default=10_000)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--endpoints",
        help="Comma-separated subset of endpoints to fetch. Defaults to all supported endpoints.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional cap for debugging; stops after this many rows per endpoint.",
    )
    return parser.parse_args()


def select_endpoint_specs(raw_value: str | None) -> tuple[EndpointSpec, ...]:
    if not raw_value:
        return ENDPOINT_SPECS
    requested = {item.strip() for item in raw_value.split(",") if item.strip()}
    selected = tuple(spec for spec in ENDPOINT_SPECS if spec.name in requested)
    missing = requested.difference({spec.name for spec in selected})
    if missing:
        raise SystemExit(f"Unsupported endpoint(s): {', '.join(sorted(missing))}")
    return selected


def fetch_endpoint(
    client: httpx.Client,
    spec: EndpointSpec,
    page_size: int,
    sleep_seconds: float,
    retries: int,
    max_rows: int | None,
) -> pd.DataFrame:
    rows: list[dict] = []
    offset = 0
    page = 0

    while True:
        params = {"limit": page_size, "offset": offset, "order": f"{spec.order_by}.asc"}
        response = None
        for attempt in range(1, retries + 1):
            try:
                response = client.get(f"/{spec.name}", params=params)
                response.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == retries:
                    raise
                time.sleep(min(2 ** (attempt - 1), 8))
        assert response is not None

        batch = response.json()
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected payload for {spec.name}: expected list, got {type(batch)!r}")
        if not batch:
            break

        rows.extend(batch)
        offset += len(batch)
        page += 1
        print(f"[fetch] {spec.name}: page={page} rows={len(batch)} total={len(rows)}")

        if max_rows is not None and len(rows) >= max_rows:
            rows = rows[:max_rows]
            break
        if len(batch) < page_size:
            break
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = select_endpoint_specs(args.endpoints)

    manifest: dict[str, object] = {
        "base_url": args.base_url.rstrip("/"),
        "fetched_at": datetime.now(UTC).isoformat(),
        "page_size": args.page_size,
        "files": {},
    }

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout, follow_redirects=True) as client:
        for spec in specs:
            output_path = output_dir / f"{spec.name}.parquet"
            if output_path.exists() and not args.overwrite:
                print(f"[skip] {spec.name}: {output_path} already exists")
                frame = pd.read_parquet(output_path)
            else:
                frame = fetch_endpoint(
                    client=client,
                    spec=spec,
                    page_size=args.page_size,
                    sleep_seconds=args.sleep_seconds,
                    retries=args.retries,
                    max_rows=args.max_rows,
                )
                frame.to_parquet(output_path, index=False)
                print(f"[write] {spec.name}: {output_path} ({len(frame)} rows)")

            manifest["files"][spec.name] = {
                "path": str(output_path.relative_to(Path.cwd())),
                "rows": int(len(frame)),
                "columns": list(frame.columns),
                "endpoint": asdict(spec),
            }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[write] manifest: {manifest_path}")


if __name__ == "__main__":
    main()
