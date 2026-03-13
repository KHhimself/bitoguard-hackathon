# Label and Task Audit

## Label Definition

**Label source:** `ops.oracle_user_labels.hidden_suspicious_label`

- Value 0 = normal user (not blacklisted)
- Value 1 = blacklisted / suspicious user

This corresponds to `user_info.status` in the upstream data contract (status=1 means blacklisted).

## Critical Finding: No Blacklist Timestamp

**The blacklist label has NO reliable timestamp for when a user was first added to the blacklist.**

The `canonical.blacklist_feed.observed_at` field records when the label was *observed by the
ingestion pipeline*, not when the suspicious activity actually occurred or when the exchange
first determined the user was suspicious. This distinction is critical:

- The `observed_at` timestamp represents the date when oracle data was loaded into the system.
- It does NOT represent the date when the user first exhibited suspicious behavior.
- It does NOT represent the date when an analyst flagged the user.
- It does NOT represent the date when the user was actually blacklisted by the exchange.

## Prohibition on Forward Prediction Claims

**FORWARD EARLY-WARNING PREDICTION IS UNSUPPORTED BY THIS DATASET.**

Any claim that the system predicts future blacklisting before it occurs is not supportable with
the available data, because:

1. We have no ground-truth timestamp for when suspicious behavior began.
2. We have no ground-truth timestamp for when the user was added to the blacklist.
3. The only timestamp available (observed_at) reflects pipeline ingestion timing, not event timing.
4. The training dataset's positive examples (blacklisted users) are identified retrospectively.

Therefore, the only honest task definition is:

**CONTEMPORANEOUS RISK SCREENING:** Given a snapshot of a user's current behavioral features,
identify whether the user matches the profile of known blacklisted users.

This is a screening task, not a prediction task. It answers "does this user look like
blacklisted users?" not "will this user be blacklisted in the future?"

## Honest Task Statements

### Permitted claims:
- "The system screens users for behavioral patterns consistent with known blacklisted users."
- "Among users with anomalous behavioral patterns (as measured by IsolationForest), blacklisted
  users score significantly higher than clean users (Mann-Whitney p < 0.0001)."
- "The IsolationForest anomaly detector achieves PR-AUC=0.835 on user-level contemporaneous
  screening (compared to baseline 0.568)."

### Prohibited claims:
- "The system predicts which users will be blacklisted."
- "The system provides early warning before suspicious activity occurs."
- "The system detected fraud before the exchange was aware of it."
- "Feature X on date D predicted blacklisting on date D+N."

## Implication for Model Deployment

The model should be positioned as a **risk screening tool** that:
1. Ranks current users by anomaly score
2. Surfaces the top-K users for analyst review
3. Generates alerts for currently anomalous behavior

It should NOT be positioned as a predictive system that anticipates future blacklisting.

## Label Coverage

- Total users: 63,770 (canonical.users)
- Labeled blacklisted: 1,608 (ops.oracle_user_labels where hidden_suspicious_label=1)
- Label coverage: 1,608 / 63,770 = 2.52% of all users are blacklisted
- Training set positive rate: 1,608 / 2,832 = 56.78% (heavily overrepresented due to sampling)

The high positive rate in the training set (56.78%) does not reflect the true operational
prevalence (2.52%). Any threshold tuning or precision estimates must account for this discrepancy.
