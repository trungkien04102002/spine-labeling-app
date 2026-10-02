"""Comparison model ("model B"): the research group's MedCLIP, for reference only.

A second opinion shown next to the app's own grading, so clinicians can compare
the two. It is NOT part of the grading: nothing here touches the 11-label table,
the annotation, or the correction log, and every failure is swallowed and
logged (see `run_quietly`) -- a broken or missing model B must never cost a
doctor their result.

What it is (https://github.com/harbinger-ux/JIT-Web): a CLIP-style model that
reads ONE 2D image and scores it against one text embedding per label, giving a
yes/no per label for the whole image -- not per disc level, and no severity.
Its own web page takes an uploaded screenshot; here the image is the
mid-sagittal slice of the series the app grades, drawn the way a screenshot of
it would look (square pixels, 1-99th percentile window), then put through the
exact transform of `JIT-Web/inference.py`.

Only the image half of the model runs here. The label text embeddings never
depend on the image, so `tools/build_reference_b.py` computes them once and
saves them next to the image weights.
"""

from __future__ import annotations

import datetime
import io
import json
import logging
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import torch
from pydantic import BaseModel

from app.inference.volume_io import _read_image, to_model_orientation

logger = logging.getLogger("uvicorn.error")

WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "models" / "weights" / "reference_b"

# The sagittal model was trained on SPIDER, the axial one on Mendeley. The app
# grades a sagittal series, so that is the one run.
DATASET_BY_PLANE = {"sagittal": "SPIDER", "axial": "Mendeley"}
PLANE = "sagittal"
THRESHOLD = 0.5  # JIT-Web's default
MODEL_NAME = "MedCLIP (JIT-Web)"

RESULT_FILE = "reference_b.json"
INPUT_FILE = "reference_b_input.png"

_lock = threading.Lock()


class ReferenceLabel(BaseModel):
    label: str
    probability: float
    prediction: int


class ReferenceResult(BaseModel):
    model: str
    plane: str
    slice_index: int
    slice_count: int
    threshold: float
    #: JIT-Web's rule: when "No Finding" scores highest, every other label is
    #: reported negative whatever its probability.
    no_finding_override: bool
    results: list[ReferenceLabel]
    created_at: str


def available() -> bool:
    """Whether model B can run on this machine (weights + transformers)."""
    dataset = DATASET_BY_PLANE[PLANE]
    files = [
        WEIGHTS_DIR / "swin_config.json",
        WEIGHTS_DIR / dataset / "vision.pt",
        WEIGHTS_DIR / dataset / "text_embeds.pt",
    ]
    if not all(f.is_file() for f in files):
        return False
    try:
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


class _ImageEncoder(torch.nn.Module):
    """`medclip.MedCLIPVisionModelViT`: Swin-T, pooled, projected to 512."""

    def __init__(self, config) -> None:
        super().__init__()
        from transformers import AutoModel

        self.model = AutoModel.from_config(config)
        self.projection_head = torch.nn.Linear(768, 512, bias=False)

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        pooled = self.model(pixel_values)["pooler_output"]
        return self.projection_head(pooled)


@lru_cache(maxsize=2)
def _load(dataset: str):
    from transformers import AutoConfig

    config_dict = json.loads((WEIGHTS_DIR / "swin_config.json").read_text())
    config = AutoConfig.for_model(**config_dict)
    encoder = _ImageEncoder(config)
    state = torch.load(WEIGHTS_DIR / dataset / "vision.pt", map_location="cpu")
    vision = {
        k[len("vision_model.") :]: v for k, v in state.items() if k.startswith("vision_model.")
    }
    # Strict, unlike JIT-Web's strict=False: a key mismatch there silently
    # leaves random weights in place, and the scores would still look plausible.
    encoder.load_state_dict(vision, strict=True)
    encoder.to(_device()).eval()
    # MedCLIPModel.compute_logits clamps the learned temperature to [0, ln 100].
    logit_scale = float(torch.clamp(state["logit_scale"], 0, 4.6052).exp())
    text = torch.load(WEIGHTS_DIR / dataset / "text_embeds.pt", map_location="cpu")
    return encoder, list(text["labels"]), text["embeds"].to(_device()), logit_scale


def mid_sagittal_png(volume_path: str) -> tuple[bytes, int, int]:
    """The mid-sagittal slice as an 8-bit PNG, as it would look on screen.

    Returns ``(png_bytes, slice_index, slice_count)``.
    """
    from PIL import Image

    image = to_model_orientation(_read_image(volume_path))
    arr = sitk.GetArrayFromImage(image).astype(np.float32)  # (S, H, W): R, I, P
    index = arr.shape[0] // 2
    frame = arr[index]
    lo, hi = np.percentile(frame, [1, 99])
    gray = (np.clip((frame - lo) / (hi - lo + 1e-8), 0, 1) * 255).astype(np.uint8)

    # A screenshot has square pixels; the voxels often are not (0.6 x 0.7 mm).
    sx, sy, _ = image.GetSpacing()  # x = columns (P), y = rows (I)
    h, w = gray.shape
    base = min(sx, sy)
    size = (max(1, round(w * sx / base)), max(1, round(h * sy / base)))
    pil = Image.fromarray(gray)
    if size != (w, h):
        pil = pil.resize(size, Image.BILINEAR)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue(), index, arr.shape[0]


def predict_png(png: bytes, plane: str = PLANE, threshold: float = THRESHOLD):
    """Score one image, exactly as `JIT-Web/inference.py::predict` does."""
    import torchvision.transforms as T
    from PIL import Image

    encoder, labels, text_embeds, logit_scale = _load(DATASET_BY_PLANE[plane])
    transform = T.Compose(
        [
            T.Resize(256, interpolation=T.InterpolationMode.BICUBIC),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
    pixels = transform(Image.open(io.BytesIO(png)).convert("RGB")).unsqueeze(0)
    with _lock, torch.no_grad():
        emb = encoder(pixels.to(_device()))
        emb = emb / emb.norm(dim=-1, keepdim=True)
        logits = emb @ text_embeds.t() * logit_scale
        probs = torch.sigmoid(logits).cpu().numpy().flatten()

    no_finding = labels.index("No Finding") if "No Finding" in labels else -1
    override = no_finding != -1 and int(np.argmax(probs)) == no_finding
    results = []
    for i, label in enumerate(labels):
        p = float(probs[i])
        pred = int(i == no_finding) if override else int(p > threshold)
        results.append(ReferenceLabel(label=label, probability=round(p, 4), prediction=pred))
    results.sort(key=lambda r: r.probability, reverse=True)
    return results, override


def run(volume_path: str, study_dir: Path) -> ReferenceResult:
    """Run model B on a study's graded series and save result + input image."""
    png, index, count = mid_sagittal_png(volume_path)
    results, override = predict_png(png)
    result = ReferenceResult(
        model=f"{MODEL_NAME} {DATASET_BY_PLANE[PLANE]}",
        plane=PLANE,
        slice_index=index,
        slice_count=count,
        threshold=THRESHOLD,
        no_finding_override=override,
        results=results,
        created_at=datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / INPUT_FILE).write_bytes(png)
    (study_dir / RESULT_FILE).write_text(result.model_dump_json(indent=2))
    return result


def run_quietly(study_id: str, volume_path: str, study_dir: Path) -> None:
    """`run`, for use after the app's own grading: never raises."""
    if not available():
        return
    try:
        run(volume_path, study_dir)
        logger.info("[reference_b %s] done", study_id)
    except Exception:
        logger.exception("[reference_b %s] FAILED (the app's own grading is unaffected)", study_id)


def load_result(study_dir: Path) -> ReferenceResult | None:
    path = study_dir / RESULT_FILE
    if not path.is_file():
        return None
    return ReferenceResult.model_validate_json(path.read_text())
