from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from config import load_settings
from db.store import DuckDBStore


FEATURE_VERSION = "v1"


@dataclass
class SnapshotContext:
    snapshot_date: pd.Timestamp
    snapshot_end: pd.Timestamp
    lookback_7d: pd.Timestamp
    lookback_30d: pd.Timestamp
    active_users: pd.DataFrame


def _prep_timeframe(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    copied = frame.copy()
    copied[column] = pd.to_datetime(copied[column], utc=True)
    return copied


def _normalize_snapshot_dates(snapshot_dates: object) -> pd.DatetimeIndex:
    if isinstance(snapshot_dates, pd.Timestamp) or not isinstance(snapshot_dates, (pd.Index, pd.Series, list, tuple, set)):
        values = [snapshot_dates]
    else:
        values = list(snapshot_dates)
    normalized = pd.DatetimeIndex(pd.to_datetime(values, utc=True)).tz_localize(None).normalize()
    return pd.DatetimeIndex(sorted(normalized.unique()))


def _user_ids_by_day(frame: pd.DataFrame, time_col: str) -> dict[pd.Timestamp, set[str]]:
    if frame.empty:
        return {}
    daily_user_ids = (
        frame.dropna(subset=["user_id", time_col])
        .assign(snapshot_date=lambda df: df[time_col].dt.tz_localize(None).dt.normalize())
        .groupby("snapshot_date")["user_id"]
        .unique()
    )
    return {
        snapshot_date: set(user_ids.tolist())
        for snapshot_date, user_ids in daily_user_ids.items()
    }


def _combined_user_ids_by_day(*frames: tuple[pd.DataFrame, str]) -> dict[pd.Timestamp, set[str]]:
    combined: defaultdict[pd.Timestamp, set[str]] = defaultdict(set)
    for frame, time_col in frames:
        for snapshot_date, user_ids in _user_ids_by_day(frame, time_col).items():
            combined[snapshot_date].update(user_ids)
    return dict(combined)


def iter_eligible_users_by_snapshot(
    users: pd.DataFrame,
    snapshot_dates: pd.DatetimeIndex,
    blacklist_feed: pd.DataFrame,
    *activity_frames: tuple[pd.DataFrame, str],
    force_include_ids: set[str] | None = None,
):
    if len(snapshot_dates) == 0:
        return

    normalized_snapshot_dates = _normalize_snapshot_dates(snapshot_dates)
    requested_snapshot_dates = set(normalized_snapshot_dates)
    iteration_dates = pd.date_range(normalized_snapshot_dates[0], normalized_snapshot_dates[-1], freq="D")
    recent_activity_by_day = _combined_user_ids_by_day(*activity_frames)
    blacklist_by_day = _combined_user_ids_by_day((blacklist_feed, "observed_at"))

    recent_activity_counts: defaultdict[str, int] = defaultdict(int)
    blacklisted_users: set[str] = set()
    first_snapshot_date = normalized_snapshot_dates[0]
    initial_window_start = first_snapshot_date - pd.Timedelta(days=29)

    for snapshot_date, user_ids in recent_activity_by_day.items():
        if initial_window_start <= snapshot_date < first_snapshot_date:
            for user_id in user_ids:
                recent_activity_counts[user_id] += 1

    for snapshot_date, user_ids in blacklist_by_day.items():
        if snapshot_date < first_snapshot_date:
            blacklisted_users.update(user_ids)

    for snapshot_date in iteration_dates:
        for user_id in recent_activity_by_day.get(snapshot_date, set()):
            recent_activity_counts[user_id] += 1

        expired_snapshot = snapshot_date - pd.Timedelta(days=30)
        for user_id in recent_activity_by_day.get(expired_snapshot, set()):
            remaining = recent_activity_counts[user_id] - 1
            if remaining > 0:
                recent_activity_counts[user_id] = remaining
            else:
                recent_activity_counts.pop(user_id, None)

        blacklisted_users.update(blacklist_by_day.get(snapshot_date, set()))

        if snapshot_date not in requested_snapshot_dates:
            continue

        snapshot_end = snapshot_date.tz_localize("UTC") + pd.Timedelta(days=1)
        eligible_user_ids = set(recent_activity_counts) | blacklisted_users
        if force_include_ids:
            eligible_user_ids |= force_include_ids
        eligible_users = users.iloc[0:0].copy()
        if eligible_user_ids:
            eligible_users = users[
                (users["created_at"] < snapshot_end)
                & (users["user_id"].isin(eligible_user_ids))
            ].copy()

        yield snapshot_date, snapshot_end, eligible_users, set(blacklisted_users)


def _sum_by_user(frame: pd.DataFrame, mask: pd.Series, value_col: str, output_name: str) -> pd.DataFrame:
    subset = frame[mask]
    if subset.empty:
        return pd.DataFrame(columns=["user_id", output_name])
    result = subset.groupby("user_id")[value_col].sum().reset_index()
    return result.rename(columns={value_col: output_name})


def _count_by_user(frame: pd.DataFrame, mask: pd.Series, output_name: str) -> pd.DataFrame:
    subset = frame[mask]
    if subset.empty:
        return pd.DataFrame(columns=["user_id", output_name])
    result = subset.groupby("user_id").size().reset_index(name=output_name)
    return result


def _avg_by_user(frame: pd.DataFrame, mask: pd.Series, value_col: str, output_name: str) -> pd.DataFrame:
    subset = frame[mask]
    if subset.empty:
        return pd.DataFrame(columns=["user_id", output_name])
    result = subset.groupby("user_id")[value_col].mean().reset_index()
    return result.rename(columns={value_col: output_name})


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    # Use float("nan") so the result stays float64 dtype (avoids pd.NA object dtype downcasting)
    denom = denominator.where(denominator != 0, other=float("nan"))
    return (numerator / denom).fillna(0.0)


def _velocity_features(
    fiat_transactions: pd.DataFrame,
    crypto_transactions: pd.DataFrame,
    snapshot_end: pd.Timestamp,
    lookback_start: pd.Timestamp,
) -> pd.DataFrame:
    deposits = fiat_transactions[
        (fiat_transactions["direction"] == "deposit")
        & (fiat_transactions["occurred_at"] >= lookback_start)
        & (fiat_transactions["occurred_at"] < snapshot_end)
    ].copy()
    withdrawals = crypto_transactions[
        (crypto_transactions["direction"] == "withdrawal")
        & (crypto_transactions["occurred_at"] >= lookback_start)
        & (crypto_transactions["occurred_at"] < snapshot_end)
    ].copy()
    if deposits.empty or withdrawals.empty:
        return pd.DataFrame(columns=[
            "user_id", "fiat_in_to_crypto_out_2h", "fiat_in_to_crypto_out_6h", "fiat_in_to_crypto_out_24h",
            "avg_dwell_time", "min_dwell_time_hours", "quick_inout_count_24h", "large_deposit_withdraw_gap",
        ])

    merged = deposits.merge(withdrawals, on="user_id", suffixes=("_fiat", "_crypto"))
    merged = merged[merged["occurred_at_crypto"] >= merged["occurred_at_fiat"]].copy()
    merged["gap_hours"] = (
        (merged["occurred_at_crypto"] - merged["occurred_at_fiat"]).dt.total_seconds() / 3600.0
    )
    if merged.empty:
        return pd.DataFrame(columns=[
            "user_id", "fiat_in_to_crypto_out_2h", "fiat_in_to_crypto_out_6h", "fiat_in_to_crypto_out_24h",
            "avg_dwell_time", "min_dwell_time_hours", "quick_inout_count_24h", "large_deposit_withdraw_gap",
        ])

    merged["within_2h"] = merged["gap_hours"] <= 2
    merged["within_6h"] = merged["gap_hours"] <= 6
    merged["within_24h"] = merged["gap_hours"] <= 24
    earliest = merged.sort_values(["user_id", "occurred_at_fiat", "gap_hours"]).drop_duplicates(["user_id", "fiat_txn_id"])
    avg_gap = earliest.groupby("user_id")["gap_hours"].mean().reset_index(name="avg_dwell_time")
    # Minimum dwell time: fastest single fiat-deposit-to-crypto-withdrawal cycle (in hours).
    # This is the primary "quick in/out retention time" (快進快出之滯留時間) signal.
    min_gap = earliest.groupby("user_id")["gap_hours"].min().reset_index(name="min_dwell_time_hours")
    # Count of sub-24h pairs: how many times did the user complete a full fiat→crypto cycle within 24h.
    quick_count = (
        earliest[earliest["within_24h"]]
        .groupby("user_id")
        .size()
        .reset_index(name="quick_inout_count_24h")
    )
    large_deposit = deposits.sort_values(["user_id", "amount_twd"], ascending=[True, False]).drop_duplicates("user_id")
    large_gap = (
        large_deposit[["user_id", "fiat_txn_id"]]
        .merge(earliest[["user_id", "fiat_txn_id", "gap_hours"]], on=["user_id", "fiat_txn_id"], how="left")
        .rename(columns={"gap_hours": "large_deposit_withdraw_gap"})
    )
    flags = earliest.groupby("user_id")[["within_2h", "within_6h", "within_24h"]].max().reset_index()
    flags = flags.rename(columns={
        "within_2h": "fiat_in_to_crypto_out_2h",
        "within_6h": "fiat_in_to_crypto_out_6h",
        "within_24h": "fiat_in_to_crypto_out_24h",
    })
    result = (
        flags
        .merge(avg_gap, on="user_id", how="outer")
        .merge(min_gap, on="user_id", how="outer")
        .merge(quick_count, on="user_id", how="outer")
        .merge(large_gap, on="user_id", how="outer")
    )
    return result.fillna({
        "fiat_in_to_crypto_out_2h": False,
        "fiat_in_to_crypto_out_6h": False,
        "fiat_in_to_crypto_out_24h": False,
        "avg_dwell_time": 0.0,
        "min_dwell_time_hours": 0.0,
        "quick_inout_count_24h": 0.0,
        "large_deposit_withdraw_gap": 0.0,
    })


def _night_ratio(frame: pd.DataFrame, time_col: str) -> pd.Series:
    hours = frame[time_col].dt.hour
    return hours.isin([0, 1, 2, 3, 4, 5]).groupby(frame["user_id"]).mean()


def _add_peer_deviation_features(result: pd.DataFrame) -> pd.DataFrame:
    """Add cohort peer-deviation features (Module 2).

    Computes within-cohort percentile ranks for key financial metrics,
    making anomaly detection cohort-aware rather than absolute-threshold-based.
    Cohort is defined by kyc_level so level-1 and level-2 users are compared
    against peers at the same verification tier.
    """
    out = result.copy()
    cohort_col = "kyc_level"
    metric_cols = [
        "fiat_in_30d",
        "fiat_out_30d",
        "trade_notional_30d",
        "crypto_withdraw_30d",
        "trade_count_30d",
        "geo_jump_count",
        "new_device_ratio",
        "ip_country_switch_count",
    ]
    for col in metric_cols:
        if col not in out.columns:
            continue
        peer_col = f"{col}_peer_pct"
        out[peer_col] = out.groupby(cohort_col)[col].rank(pct=True)

    # Fiat in/out imbalance: +1 = only inflows, -1 = only outflows, 0 = balanced
    total_fiat = out["fiat_in_30d"] + out["fiat_out_30d"]
    out["fiat_inout_imbalance_30d"] = _safe_ratio(
        out["fiat_in_30d"] - out["fiat_out_30d"],
        total_fiat,
    )

    # Burstiness: ratio of 7d activity to 30d activity (high = recent spike)
    fiat_7d_sum = out.get("fiat_in_7d", pd.Series(0.0, index=out.index)) + out.get("fiat_out_7d", pd.Series(0.0, index=out.index))
    fiat_30d_sum = total_fiat.where(total_fiat != 0, other=float("nan"))
    out["activity_burst_7d_30d"] = (fiat_7d_sum / fiat_30d_sum).fillna(0.0)
    # Clamp to [0, 1] — values above 1 indicate most activity was in the last 7d window
    out["activity_burst_7d_30d"] = out["activity_burst_7d_30d"].clip(upper=1.0)

    # Declared-vs-actual volume deviation (within cohort, as a z-score proxy)
    if "actual_volume_expected_ratio" in out.columns:
        peer_mean = out.groupby(cohort_col)["actual_volume_expected_ratio"].transform("mean")
        peer_std_raw = out.groupby(cohort_col)["actual_volume_expected_ratio"].transform("std")
        peer_std = peer_std_raw.where(peer_std_raw != 0, other=float("nan"))
        out["volume_ratio_peer_zscore"] = ((out["actual_volume_expected_ratio"] - peer_mean) / peer_std).fillna(0.0)

    return out


def build_feature_snapshots(
    snapshot_dates: pd.DatetimeIndex | None = None,
    target_user_ids: set[str] | None = None,
    force_include_ids: set[str] | None = None,
    persist: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    settings = load_settings()
    store = DuckDBStore(settings.db_path)

    users = _prep_timeframe(store.read_table("canonical.users"), "created_at")
    fiat = _prep_timeframe(store.read_table("canonical.fiat_transactions"), "occurred_at")
    trade = _prep_timeframe(store.read_table("canonical.trade_orders"), "occurred_at")
    crypto = _prep_timeframe(store.read_table("canonical.crypto_transactions"), "occurred_at")
    login = _prep_timeframe(store.read_table("canonical.login_events"), "occurred_at")
    blacklist_feed = _prep_timeframe(store.read_table("canonical.blacklist_feed"), "observed_at")
    target_user_filter = set(target_user_ids) if target_user_ids is not None else None
    use_targeted_graph = snapshot_dates is not None or target_user_filter is not None or not persist

    if target_user_filter is not None:
        users = users[users["user_id"].isin(target_user_filter)].copy()
        fiat = fiat[fiat["user_id"].isin(target_user_filter)].copy()
        trade = trade[trade["user_id"].isin(target_user_filter)].copy()
        crypto = crypto[crypto["user_id"].isin(target_user_filter)].copy()
        login = login[login["user_id"].isin(target_user_filter)].copy()

    if snapshot_dates is None:
        _time_series = [
            s for s in [fiat["occurred_at"], trade["occurred_at"], crypto["occurred_at"], login["occurred_at"]]
            if not s.empty
        ]
        all_times = pd.concat(_time_series, ignore_index=True).dropna() if _time_series else pd.Series(dtype="datetime64[ns, UTC]")
        if all_times.empty:
            feature_day = pd.DataFrame()
            feature_30d = pd.DataFrame()
            if persist:
                store.replace_table("features.feature_snapshots_user_30d", feature_30d)
                store.replace_table("features.feature_snapshots_user_day", feature_day)
            return feature_day, feature_30d
        snapshot_dates = pd.date_range(all_times.dt.date.min(), all_times.dt.date.max(), freq="D")
    else:
        snapshot_dates = _normalize_snapshot_dates(snapshot_dates)

    graph = store.read_table("features.graph_features")
    graph["snapshot_date"] = pd.to_datetime(graph["snapshot_date"])

    if use_targeted_graph and target_user_filter is not None:
        requested_pairs = {
            (user_id, pd.Timestamp(snapshot_date))
            for user_id in target_user_filter
            for snapshot_date in snapshot_dates
        }
        existing_pairs = {
            (row["user_id"], pd.Timestamp(row["snapshot_date"]))
            for _, row in graph[
                graph["user_id"].isin(target_user_filter)
                & (graph["snapshot_date"].isin(snapshot_dates))
            ][["user_id", "snapshot_date"]].iterrows()
        }
        if not requested_pairs.issubset(existing_pairs):
            from features.graph_features import build_graph_features

            graph = build_graph_features(
                snapshot_dates=snapshot_dates,
                target_user_ids=target_user_filter,
                persist=False,
            )
            graph["snapshot_date"] = pd.to_datetime(graph["snapshot_date"])
    elif use_targeted_graph:
        from features.graph_features import build_graph_features

        graph = build_graph_features(
            snapshot_dates=snapshot_dates,
            target_user_ids=target_user_filter,
            persist=False,
        )
        graph["snapshot_date"] = pd.to_datetime(graph["snapshot_date"])

    if len(snapshot_dates) == 0:
        feature_day = pd.DataFrame()
        feature_30d = pd.DataFrame()
        if persist:
            store.replace_table("features.feature_snapshots_user_30d", feature_30d)
            store.replace_table("features.feature_snapshots_user_day", feature_day)
        return feature_day, feature_30d

    user_day_records: list[pd.DataFrame] = []
    user_30d_records: list[pd.DataFrame] = []

    for snapshot_date, snapshot_end, eligible_users, _ in iter_eligible_users_by_snapshot(
        users,
        snapshot_dates,
        blacklist_feed,
        (fiat, "occurred_at"),
        (trade, "occurred_at"),
        (crypto, "occurred_at"),
        (login, "occurred_at"),
        force_include_ids=force_include_ids,
    ):
        active_users = eligible_users
        if target_user_filter is not None:
            active_users = users[users["created_at"] < snapshot_end].copy()

        ctx = SnapshotContext(
            snapshot_date=snapshot_date,
            snapshot_end=snapshot_end,
            lookback_7d=snapshot_end - pd.Timedelta(days=7),
            lookback_30d=snapshot_end - pd.Timedelta(days=30),
            active_users=active_users,
        )
        if ctx.active_users.empty:
            continue
        base = ctx.active_users[[
            "user_id", "kyc_level", "occupation", "monthly_income_twd",
            "expected_monthly_volume_twd", "declared_source_of_funds", "segment",
        ]].copy()
        base["snapshot_date"] = snapshot_date
        base["feature_version"] = FEATURE_VERSION
        base["feature_snapshot_id"] = base["user_id"].map(lambda uid: f"f30_{uid}_{snapshot_date.date().isoformat()}")

        fiat_1d = _sum_by_user(
            fiat,
            (fiat["occurred_at"] >= snapshot_end - pd.Timedelta(days=1)) & (fiat["occurred_at"] < snapshot_end) & (fiat["direction"] == "deposit"),
            "amount_twd",
            "fiat_in_1d",
        ).merge(
            _sum_by_user(
                fiat,
                (fiat["occurred_at"] >= snapshot_end - pd.Timedelta(days=1)) & (fiat["occurred_at"] < snapshot_end) & (fiat["direction"] == "withdrawal"),
                "amount_twd",
                "fiat_out_1d",
            ),
            on="user_id",
            how="outer",
        )
        fiat_7d = _sum_by_user(
            fiat,
            (fiat["occurred_at"] >= ctx.lookback_7d) & (fiat["occurred_at"] < snapshot_end) & (fiat["direction"] == "deposit"),
            "amount_twd",
            "fiat_in_7d",
        ).merge(
            _sum_by_user(
                fiat,
                (fiat["occurred_at"] >= ctx.lookback_7d) & (fiat["occurred_at"] < snapshot_end) & (fiat["direction"] == "withdrawal"),
                "amount_twd",
                "fiat_out_7d",
            ),
            on="user_id",
            how="outer",
        )
        fiat_30d = _sum_by_user(
            fiat,
            (fiat["occurred_at"] >= ctx.lookback_30d) & (fiat["occurred_at"] < snapshot_end) & (fiat["direction"] == "deposit"),
            "amount_twd",
            "fiat_in_30d",
        ).merge(
            _sum_by_user(
                fiat,
                (fiat["occurred_at"] >= ctx.lookback_30d) & (fiat["occurred_at"] < snapshot_end) & (fiat["direction"] == "withdrawal"),
                "amount_twd",
                "fiat_out_30d",
            ),
            on="user_id",
            how="outer",
        )
        trade_stats = (
            _count_by_user(trade, (trade["occurred_at"] >= ctx.lookback_30d) & (trade["occurred_at"] < snapshot_end), "trade_count_30d")
            .merge(_sum_by_user(trade, (trade["occurred_at"] >= ctx.lookback_30d) & (trade["occurred_at"] < snapshot_end), "notional_twd", "trade_notional_30d"), on="user_id", how="outer")
        )
        crypto_stats = _sum_by_user(
            crypto,
            (crypto["occurred_at"] >= ctx.lookback_30d) & (crypto["occurred_at"] < snapshot_end) & (crypto["direction"] == "withdrawal"),
            "amount_twd_equiv",
            "crypto_withdraw_30d",
        )
        velocity = _velocity_features(fiat, crypto, snapshot_end, ctx.lookback_30d)

        login_window = login[(login["occurred_at"] >= ctx.lookback_30d) & (login["occurred_at"] < snapshot_end)].copy()
        login_window["night_flag"] = login_window["occurred_at"].dt.hour.isin([0, 1, 2, 3, 4, 5])
        login_features = (
            _count_by_user(login_window, login_window["is_geo_jump"], "geo_jump_count")
            .merge(_avg_by_user(login_window, login_window["user_id"].notna(), "is_vpn", "vpn_ratio"), on="user_id", how="outer")
            .merge(_avg_by_user(login_window, login_window["user_id"].notna(), "is_new_device", "new_device_ratio"), on="user_id", how="outer")
        )
        if not login_window.empty:
            login_features = login_features.merge(
                login_window.groupby("user_id")["ip_country"].nunique().reset_index(name="ip_country_switch_count"),
                on="user_id",
                how="outer",
            )
            login_features = login_features.merge(
                _night_ratio(login_window, "occurred_at").reset_index(name="night_login_ratio"),
                on="user_id",
                how="outer",
            )
        else:
            login_features["ip_country_switch_count"] = 0
            login_features["night_login_ratio"] = 0.0

        withdrawal_day = crypto[(crypto["occurred_at"] >= snapshot_end - pd.Timedelta(days=1)) & (crypto["occurred_at"] < snapshot_end) & (crypto["direction"] == "withdrawal")].copy()
        if not withdrawal_day.empty:
            withdrawal_day["night_large_flag"] = (
                withdrawal_day["occurred_at"].dt.hour.isin([0, 1, 2, 3, 4, 5]) & (withdrawal_day["amount_twd_equiv"] >= 50000)
            )
            night_large = withdrawal_day.groupby("user_id")["night_large_flag"].mean().reset_index(name="night_large_withdrawal_ratio")
        else:
            night_large = pd.DataFrame(columns=["user_id", "night_large_withdrawal_ratio"])

        new_device_withdraw = pd.DataFrame(columns=["user_id", "new_device_withdrawal_24h"])
        if not login_window.empty and not crypto.empty:
            new_device_events = login_window[login_window["is_new_device"]][["user_id", "occurred_at"]].rename(columns={"occurred_at": "login_time"})
            withdrawals = crypto[(crypto["direction"] == "withdrawal") & (crypto["occurred_at"] < snapshot_end)][["user_id", "occurred_at"]].rename(columns={"occurred_at": "withdraw_time"})
            joined = new_device_events.merge(withdrawals, on="user_id", how="inner")
            joined = joined[(joined["withdraw_time"] >= joined["login_time"]) & (joined["withdraw_time"] <= joined["login_time"] + pd.Timedelta(hours=24))]
            if not joined.empty:
                new_device_withdraw = joined.groupby("user_id").size().reset_index(name="new_device_withdrawal_24h")
                new_device_withdraw["new_device_withdrawal_24h"] = True

        result_30 = base.merge(fiat_1d, on="user_id", how="left") \
            .merge(fiat_7d, on="user_id", how="left") \
            .merge(fiat_30d, on="user_id", how="left") \
            .merge(trade_stats, on="user_id", how="left") \
            .merge(crypto_stats, on="user_id", how="left") \
            .merge(velocity, on="user_id", how="left") \
            .merge(login_features, on="user_id", how="left") \
            .merge(night_large, on="user_id", how="left") \
            .merge(new_device_withdraw, on="user_id", how="left") \
            .merge(graph[graph["snapshot_date"] == snapshot_date][[
                "user_id", "shared_device_count", "shared_bank_count", "shared_wallet_count",
                "blacklist_1hop_count", "blacklist_2hop_count", "component_size", "fan_out_ratio"
            ]], on="user_id", how="left")
        # Opt into future pandas downcasting behavior so fillna does not warn.
        # infer_objects(copy=False) then coerces remaining object-dtype columns to proper types.
        with pd.option_context("future.no_silent_downcasting", True):
            result_30 = result_30.fillna({
                "fiat_in_1d": 0.0, "fiat_out_1d": 0.0, "fiat_in_7d": 0.0, "fiat_out_7d": 0.0, "fiat_in_30d": 0.0, "fiat_out_30d": 0.0,
                "trade_count_30d": 0.0, "trade_notional_30d": 0.0, "crypto_withdraw_30d": 0.0,
                "avg_dwell_time": 0.0, "min_dwell_time_hours": 0.0, "quick_inout_count_24h": 0.0, "large_deposit_withdraw_gap": 0.0,
                "geo_jump_count": 0.0, "vpn_ratio": 0.0, "new_device_ratio": 0.0, "ip_country_switch_count": 0.0, "night_login_ratio": 0.0,
                "night_large_withdrawal_ratio": 0.0,
                "shared_device_count": 0.0, "shared_bank_count": 0.0, "shared_wallet_count": 0.0, "blacklist_1hop_count": 0.0,
                "blacklist_2hop_count": 0.0, "component_size": 1.0, "fan_out_ratio": 0.0,
            }).infer_objects(copy=False)
        # Bool columns: cast via notna() mask to guarantee bool dtype with no downcasting
        for _bool_col in ("fiat_in_to_crypto_out_2h", "fiat_in_to_crypto_out_6h", "fiat_in_to_crypto_out_24h", "new_device_withdrawal_24h"):
            if _bool_col in result_30.columns:
                _col = result_30[_bool_col]
                result_30[_bool_col] = _col.notna() & _col.astype(object).map(lambda v: bool(v) if v is not None and str(v) not in ("", "nan", "None") else False)
        result_30["actual_volume_expected_ratio"] = _safe_ratio(result_30["trade_notional_30d"], result_30["expected_monthly_volume_twd"])
        result_30["actual_fiat_income_ratio"] = _safe_ratio(result_30["fiat_in_30d"] + result_30["fiat_out_30d"], result_30["monthly_income_twd"])
        result_30 = _add_peer_deviation_features(result_30)

        result_day = result_30.copy()
        result_day["feature_snapshot_id"] = result_day["user_id"].map(lambda uid: f"fd_{uid}_{snapshot_date.date().isoformat()}")

        user_30d_records.append(result_30)
        user_day_records.append(result_day)

    feature_30d = pd.concat(user_30d_records, ignore_index=True) if user_30d_records else pd.DataFrame()
    feature_day = pd.concat(user_day_records, ignore_index=True) if user_day_records else pd.DataFrame()
    if persist:
        store.replace_table("features.feature_snapshots_user_30d", feature_30d)
        store.replace_table("features.feature_snapshots_user_day", feature_day)
    return feature_day, feature_30d


if __name__ == "__main__":
    build_feature_snapshots()
