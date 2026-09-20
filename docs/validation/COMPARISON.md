# Grading vs. radiologist, on studies the model never trained on

Eight RSNA studies drawn from `backend/data/holdout_frozen`, whose
MANIFEST marks them as validation-split patients never used for
training. Ground truth is `train.csv` from the RSNA 2024 challenge.

Only the three conditions the app's fine-tuned CBAM model answers are
scored. The other 8 labels in the UI come from upstream SpineNet, which
this dataset has no ground truth for.

`=` the app matched the radiologist, `x` it did not.

## 1106510276 — severe canal stenosis

App study id `VAL-1106510276` · matched 8/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Normal/Mild / Severe x | Normal/Mild / Normal/Mild = | Moderate / Normal/Mild x |
| L2-L3 | Severe / Severe = | Moderate / Normal/Mild x | Moderate / Normal/Mild x |
| L3-L4 | Severe / Severe = | Normal/Mild / Normal/Mild = | Moderate / Normal/Mild x |
| L4-L5 | Normal/Mild / Moderate x | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L5-S1 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Moderate x |

## 1179643011 — severe canal stenosis

App study id `VAL-1179643011` · matched 10/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Severe / Severe = | Moderate / Normal/Mild x | Moderate / Normal/Mild x |
| L2-L3 | Severe / Severe = | Normal/Mild / Normal/Mild = | Moderate / Normal/Mild x |
| L3-L4 | Severe / Severe = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L4-L5 | Normal/Mild / Moderate x | Normal/Mild / Normal/Mild = | Moderate / Normal/Mild x |
| L5-S1 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Moderate / Moderate = |

## 1703545013 — severe canal stenosis

App study id `VAL-1703545013` · matched 10/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L2-L3 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Moderate x |
| L3-L4 | Moderate / Severe x | Normal/Mild / Normal/Mild = | Normal/Mild / Moderate x |
| L4-L5 | Severe / Severe = | Moderate / Moderate = | Moderate / Normal/Mild x |
| L5-S1 | Severe / Severe = | Moderate / Moderate = | Moderate / Normal/Mild x |

## 189360935 — severe foraminal narrowing

App study id `VAL-189360935` · matched 5/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Normal/Mild / Normal/Mild = | Normal/Mild / Moderate x | Moderate / Normal/Mild x |
| L2-L3 | Moderate / Normal/Mild x | Moderate / Moderate = | Moderate / Moderate = |
| L3-L4 | Moderate / Normal/Mild x | Moderate / Normal/Mild x | Moderate / Moderate = |
| L4-L5 | Moderate / Normal/Mild x | Moderate / Severe x | Moderate / Severe x |
| L5-S1 | Normal/Mild / Normal/Mild = | Moderate / Severe x | Moderate / Severe x |

## 344297746 — severe foraminal narrowing

App study id `VAL-344297746` · matched 5/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Moderate / Moderate = | Moderate / Normal/Mild x | Normal/Mild / Moderate x |
| L2-L3 | Severe / Moderate x | Moderate / Moderate = | Moderate / Normal/Mild x |
| L3-L4 | Moderate / Normal/Mild x | Moderate / Moderate = | Normal/Mild / Moderate x |
| L4-L5 | Normal/Mild / Normal/Mild = | Normal/Mild / Severe x | Normal/Mild / Severe x |
| L5-S1 | Severe / Normal/Mild x | Moderate / Moderate = | Moderate / Severe x |

## 1545888499 — severe foraminal narrowing

App study id `VAL-1545888499` · matched 12/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L2-L3 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L3-L4 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L4-L5 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L5-S1 | Normal/Mild / Moderate x | Moderate / Severe x | Moderate / Severe x |

## 1518597578 — normal / mild throughout

App study id `VAL-1518597578` · matched 14/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L2-L3 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L3-L4 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L4-L5 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L5-S1 | Moderate / Normal/Mild x | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |

## 2248929238 — normal / mild throughout

App study id `VAL-2248929238` · matched 14/15 cells

| Level | Canal (app / doctor) | Left foraminal | Right foraminal |
|---|---|---|---|
| L1-L2 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L2-L3 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L3-L4 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L4-L5 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = |
| L5-S1 | Normal/Mild / Normal/Mild = | Normal/Mild / Normal/Mild = | Moderate / Normal/Mild x |

## Summary

Overall: **78/120 cells correct (65.0%)**

Per condition:

| Condition | Correct | Cells | Accuracy |
|---|---|---|---|
| canal_stenosis | 28 | 40 | 70.0% |
| left_foraminal | 31 | 40 | 77.5% |
| right_foraminal | 19 | 40 | 47.5% |

Per ground-truth severity (does it ever say Severe?):

| Ground truth | Correct | Cells | Recall |
|---|---|---|---|
| Normal/Mild | 61 | 82 | 74.4% |
| Moderate | 10 | 20 | 50.0% |
| Severe | 7 | 18 | 38.9% |

What the app actually predicted, counted: Normal/Mild 73, Moderate 38, Severe 9
