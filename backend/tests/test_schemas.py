from app.schemas import GradingItem, InferResult, SegmentationResult

SAMPLE = {
    "study_id": "study-uuid-1",
    "segmentation": {
        "mask_uri": "/data/studies/study-uuid-1/mask.npy",
        "labels": {1: "L1", 2: "L2", 3: "L3"},
    },
    "grading": [
        {
            "level": "L4-L5",
            "condition": "spinal_canal_stenosis",
            "severity": "severe",
            "score": 0.92,
            "bbox": [10.0, 20.0, 30.0, 40.0],
            "heatmap_uri": "/data/studies/study-uuid-1/heatmap_l4_l5.png",
        },
        {
            "level": "L5-S1",
            "condition": "left_neural_foraminal_narrowing",
            "severity": "moderate",
            "score": 0.55,
        },
    ],
    "model_version": "v3-cbam-1.0",
}


def test_infer_result_round_trip():
    result = InferResult.model_validate(SAMPLE)

    assert isinstance(result.segmentation, SegmentationResult)
    assert all(isinstance(item, GradingItem) for item in result.grading)

    dumped = result.model_dump()

    assert dumped["study_id"] == SAMPLE["study_id"]
    assert dumped["segmentation"]["mask_uri"] == SAMPLE["segmentation"]["mask_uri"]
    assert dumped["segmentation"]["labels"] == SAMPLE["segmentation"]["labels"]
    assert dumped["model_version"] == SAMPLE["model_version"]

    assert len(dumped["grading"]) == 2
    assert dumped["grading"][0]["level"] == "L4-L5"
    assert dumped["grading"][0]["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert dumped["grading"][0]["heatmap_uri"] == (
        "/data/studies/study-uuid-1/heatmap_l4_l5.png"
    )

    # Optional fields default to None when omitted.
    assert dumped["grading"][1]["bbox"] is None
    assert dumped["grading"][1]["heatmap_uri"] is None
