from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


DEFAULT_RAW_DIR = Path("data/aws_event/raw")
DEFAULT_OUTPUT_DIR = Path("data/aws_event/clean")
DECIMAL_SCALE = 1e-8

SEX_MAP = {0: "unknown", 1: "male", 2: "female"}
USER_SOURCE_MAP = {0: "web", 1: "app"}
TRANSFER_KIND_MAP = {0: "deposit", 1: "withdrawal"}
CRYPTO_SUB_KIND_MAP = {0: "external", 1: "internal"}
PROTOCOL_MAP = {
    0: "self",
    1: "erc20",
    2: "omni",
    3: "bnb",
    4: "trc20",
    5: "bsc",
    6: "polygon",
}
TRADE_SIDE_MAP = {0: "sell_usdt_for_twd", 1: "buy_usdt_with_twd"}
ORDER_SOURCE_MAP = {0: "web", 1: "app", 2: "api"}
SWAP_KIND_MAP = {0: "buy_usdt_with_twd", 1: "sell_usdt_for_twd"}

CAREER_MAP = {
    1: "agriculture_fishery",
    2: "mining",
    3: "manufacturing",
    4: "utilities_power_gas",
    5: "water_and_environment",
    6: "construction",
    7: "wholesale_retail",
    8: "transport_storage",
    9: "hospitality_food",
    10: "publishing",
    11: "information_communication",
    12: "technology",
    13: "finance_insurance_securities",
    14: "blockchain_crypto",
    15: "real_estate",
    16: "education",
    17: "healthcare_social_work",
    18: "arts_entertainment_leisure",
    19: "services",
    20: "military_civil_service",
    21: "public_admin_defense",
    22: "freelancer",
    23: "unemployed",
    24: "student",
    25: "retired",
    26: "small_business",
    27: "professional_services",
    28: "restaurant",
    29: "jewelry_art_dealer",
    30: "nonprofit_religious",
    31: "lottery_betting",
}

INCOME_SOURCE_MAP = {
    1: "salary",
    2: "business_income",
    3: "royalty",
    4: "investment_income",
    5: "rental_income",
    6: "pension",
    7: "other_income",
    8: "inheritance_gift",
    9: "real_estate_sale",
    10: "no_income",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean official aws-event-api parquet snapshots.")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def require_parquet(raw_dir: Path, name: str) -> pd.DataFrame:
    path = raw_dir / f"{name}.parquet"
    if not path.exists():
        raise SystemExit(f"Missing raw parquet: {path}. Run scripts/fetch_aws_event_data.py first.")
    return pd.read_parquet(path)


def maybe_to_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def maybe_to_datetime(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    return frame


def map_enum(series: pd.Series, mapping: dict[int, str]) -> pd.Series:
    return series.map(mapping).fillna("unknown")


def clean_user_info(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame = maybe_to_numeric(frame, ["user_id", "sex", "age", "career", "income_source", "user_source"])
    frame = maybe_to_datetime(frame, ["confirmed_at", "level1_finished_at", "level2_finished_at"])
    frame["sex_label"] = map_enum(frame["sex"], SEX_MAP)
    frame["career_label"] = map_enum(frame["career"], CAREER_MAP)
    frame["income_source_label"] = map_enum(frame["income_source"], INCOME_SOURCE_MAP)
    frame["user_source_label"] = map_enum(frame["user_source"], USER_SOURCE_MAP)
    frame["has_email_confirmation"] = frame["confirmed_at"].notna()
    frame["has_level1_kyc"] = frame["level1_finished_at"].notna()
    frame["has_level2_kyc"] = frame["level2_finished_at"].notna()
    frame["kyc_level"] = 0
    frame.loc[frame["has_level1_kyc"], "kyc_level"] = 1
    frame.loc[frame["has_level2_kyc"], "kyc_level"] = 2
    frame["days_email_to_level1"] = (
        (frame["level1_finished_at"] - frame["confirmed_at"]).dt.total_seconds() / 86400.0
    )
    frame["days_level1_to_level2"] = (
        (frame["level2_finished_at"] - frame["level1_finished_at"]).dt.total_seconds() / 86400.0
    )
    return frame.sort_values("user_id").reset_index(drop=True)


def clean_train_label(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame = maybe_to_numeric(frame, ["user_id", "status"])
    frame["is_known_blacklist"] = frame["status"].fillna(0).astype("Int64").eq(1)
    return frame.drop_duplicates(subset=["user_id"]).sort_values("user_id").reset_index(drop=True)


def clean_predict_label(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame = maybe_to_numeric(frame, ["user_id"])
    frame["needs_prediction"] = True
    return frame.drop_duplicates(subset=["user_id"]).sort_values("user_id").reset_index(drop=True)


def clean_twd_transfer(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame = maybe_to_numeric(frame, ["id", "user_id", "kind", "ori_samount"])
    frame = maybe_to_datetime(frame, ["created_at"])
    frame = frame.rename(columns={"ori_samount": "ori_samount_raw"})
    frame["amount_twd"] = frame["ori_samount_raw"] * DECIMAL_SCALE
    frame["kind_label"] = map_enum(frame["kind"], TRANSFER_KIND_MAP)
    frame["is_deposit"] = frame["kind"].eq(0)
    frame["is_withdrawal"] = frame["kind"].eq(1)
    return frame.sort_values(["created_at", "id"], na_position="last").reset_index(drop=True)


def clean_crypto_transfer(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame = maybe_to_numeric(
        frame,
        ["id", "user_id", "kind", "sub_kind", "ori_samount", "twd_srate", "relation_user_id", "protocol"],
    )
    frame = maybe_to_datetime(frame, ["created_at"])
    frame = frame.rename(columns={"ori_samount": "ori_samount_raw", "twd_srate": "twd_srate_raw"})
    frame["amount_asset"] = frame["ori_samount_raw"] * DECIMAL_SCALE
    frame["twd_rate"] = frame["twd_srate_raw"] * DECIMAL_SCALE
    frame["amount_twd_equiv"] = frame["amount_asset"] * frame["twd_rate"]
    frame["kind_label"] = map_enum(frame["kind"], TRANSFER_KIND_MAP)
    frame["sub_kind_label"] = map_enum(frame["sub_kind"], CRYPTO_SUB_KIND_MAP)
    frame["protocol_label"] = map_enum(frame["protocol"], PROTOCOL_MAP)
    frame["is_internal_transfer"] = frame["sub_kind"].eq(1)
    frame["is_external_transfer"] = frame["sub_kind"].eq(0)
    return frame.sort_values(["created_at", "id"], na_position="last").reset_index(drop=True)


def clean_usdt_twd_trading(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame = maybe_to_numeric(
        frame,
        ["id", "user_id", "is_buy", "trade_samount", "twd_srate", "is_market", "source"],
    )
    frame = maybe_to_datetime(frame, ["updated_at"])
    frame = frame.rename(columns={"trade_samount": "trade_samount_raw", "twd_srate": "twd_srate_raw"})
    frame["trade_amount_usdt"] = frame["trade_samount_raw"] * DECIMAL_SCALE
    frame["twd_rate"] = frame["twd_srate_raw"] * DECIMAL_SCALE
    frame["trade_notional_twd"] = frame["trade_amount_usdt"] * frame["twd_rate"]
    frame["side_label"] = map_enum(frame["is_buy"], TRADE_SIDE_MAP)
    frame["order_type_label"] = frame["is_market"].map({0: "limit", 1: "market"}).fillna("unknown")
    frame["source_label"] = map_enum(frame["source"], ORDER_SOURCE_MAP)
    return frame.sort_values(["updated_at", "id"], na_position="last").reset_index(drop=True)


def clean_usdt_swap(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame = maybe_to_numeric(frame, ["id", "user_id", "kind", "twd_samount", "currency_samount"])
    frame = maybe_to_datetime(frame, ["created_at"])
    frame = frame.rename(columns={"twd_samount": "twd_samount_raw", "currency_samount": "currency_samount_raw"})
    frame["twd_amount"] = frame["twd_samount_raw"] * DECIMAL_SCALE
    frame["currency_amount"] = frame["currency_samount_raw"] * DECIMAL_SCALE
    frame["kind_label"] = map_enum(frame["kind"], SWAP_KIND_MAP)
    return frame.sort_values(["created_at", "id"], na_position="last").reset_index(drop=True)


def build_user_index(
    user_info: pd.DataFrame,
    train_label: pd.DataFrame,
    predict_label: pd.DataFrame,
) -> pd.DataFrame:
    user_ids = pd.Series(
        pd.concat(
            [
                user_info["user_id"],
                train_label["user_id"],
                predict_label["user_id"],
            ],
            ignore_index=True,
        ).dropna().unique(),
        name="user_id",
    )
    index = pd.DataFrame(user_ids).sort_values("user_id").reset_index(drop=True)
    index = index.merge(
        user_info[["user_id", "sex", "age", "career", "income_source", "user_source", "kyc_level"]],
        on="user_id",
        how="left",
    )
    index = index.merge(
        train_label[["user_id", "status", "is_known_blacklist"]],
        on="user_id",
        how="left",
    )
    index = index.merge(
        predict_label[["user_id", "needs_prediction"]],
        on="user_id",
        how="left",
    )
    index["has_profile"] = index["sex"].notna() | index["age"].notna() | index["career"].notna()
    index["needs_prediction"] = index["needs_prediction"].eq(True)
    index["is_known_blacklist"] = index["is_known_blacklist"].eq(True)
    return index


def write_frame(frame: pd.DataFrame, output_dir: Path, name: str, overwrite: bool) -> dict[str, object]:
    path = output_dir / f"{name}.parquet"
    if path.exists() and not overwrite:
        raise SystemExit(f"Refusing to overwrite existing file: {path}. Pass --overwrite to replace it.")
    frame.to_parquet(path, index=False)
    print(f"[write] {name}: {path} ({len(frame)} rows)")
    return {"path": str(path.relative_to(Path.cwd())), "rows": int(len(frame)), "columns": list(frame.columns)}


def main() -> None:
    args = parse_args()
    raw_dir = Path(args.raw_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_frames = {
        "user_info": require_parquet(raw_dir, "user_info"),
        "train_label": require_parquet(raw_dir, "train_label"),
        "predict_label": require_parquet(raw_dir, "predict_label"),
        "twd_transfer": require_parquet(raw_dir, "twd_transfer"),
        "crypto_transfer": require_parquet(raw_dir, "crypto_transfer"),
        "usdt_swap": require_parquet(raw_dir, "usdt_swap"),
        "usdt_twd_trading": require_parquet(raw_dir, "usdt_twd_trading"),
    }

    clean_frames = {
        "user_info": clean_user_info(raw_frames["user_info"]),
        "train_label": clean_train_label(raw_frames["train_label"]),
        "predict_label": clean_predict_label(raw_frames["predict_label"]),
        "twd_transfer": clean_twd_transfer(raw_frames["twd_transfer"]),
        "crypto_transfer": clean_crypto_transfer(raw_frames["crypto_transfer"]),
        "usdt_swap": clean_usdt_swap(raw_frames["usdt_swap"]),
        "usdt_twd_trading": clean_usdt_twd_trading(raw_frames["usdt_twd_trading"]),
    }
    clean_frames["user_index"] = build_user_index(
        user_info=clean_frames["user_info"],
        train_label=clean_frames["train_label"],
        predict_label=clean_frames["predict_label"],
    )

    manifest = {
        "cleaned_at": datetime.now(UTC).isoformat(),
        "raw_dir": str(raw_dir.relative_to(Path.cwd())),
        "files": {},
    }

    for name, frame in clean_frames.items():
        manifest["files"][name] = write_frame(frame, output_dir, name, overwrite=args.overwrite)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[write] manifest: {manifest_path}")


if __name__ == "__main__":
    main()
