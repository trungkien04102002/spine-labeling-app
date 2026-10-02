"""Prepare the comparison model ("model B") so the app can run it offline.

Model B is the research group's MedCLIP (Swin-T image encoder + Bio_ClinicalBERT
text encoder, https://github.com/harbinger-ux/JIT-Web). It classifies a single
2D image by comparing its embedding with one averaged text embedding per label.
Those text embeddings depend only on the weights and the label sentences, never
on the image, so they are computed here once and saved; the app then needs only
the image half of the model and no BERT download at run time.

Mirrors `inference.py::MedCLIPPredictor.load_model_for_plane` exactly: for each
label, every sentence marked positive for it is encoded in ONE padded batch
(the encoder averages over padding too, so batching changes the numbers),
each embedding is L2-normalised, the mean is taken and normalised again.

    git clone https://github.com/harbinger-ux/JIT-Web /tmp/JIT-Web
    # weights: see JIT-Web/download_weights.sh, saved as
    #   backend/models/weights/reference_b/{SPIDER,Mendeley}/pytorch_model.bin
    backend/.venv/bin/python tools/build_reference_b.py --jit-web /tmp/JIT-Web
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import torch
from torch import nn
from transformers import AutoConfig, AutoModel, AutoTokenizer

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "backend" / "models" / "weights" / "reference_b"
BERT_TYPE = "emilyalsentzer/Bio_ClinicalBERT"
VIT_TYPE = "microsoft/swin-tiny-patch4-window7-224"
DATASETS = ("SPIDER", "Mendeley")


class TextEncoder(nn.Module):
    """`medclip.MedCLIPTextModel`, forward pass unchanged."""

    def __init__(self) -> None:
        super().__init__()
        self.model = AutoModel.from_pretrained(BERT_TYPE, output_hidden_states=True)
        self.projection_head = nn.Linear(768, 512, bias=False)

    def forward(self, input_ids, attention_mask):
        out = self.model(input_ids=input_ids, attention_mask=attention_mask)
        hs = out["hidden_states"]
        stacked = torch.stack([hs[1], hs[2], hs[-1]])  # layer, batch, seq, dim
        embed = stacked.permute(1, 0, 2, 3).mean(2).mean(1)
        return self.projection_head(embed)


def build(dataset: str, jit_web: Path, tokenizer) -> None:
    weights = torch.load(
        OUT / dataset / "pytorch_model.bin", map_location="cpu", weights_only=False
    )
    encoder = TextEncoder()
    text_sd = {
        k[len("text_model.") :]: v for k, v in weights.items() if k.startswith("text_model.")
    }
    missing, unexpected = encoder.load_state_dict(text_sd, strict=False)
    # BERT's position_ids buffer is the only thing allowed to differ: older
    # transformers saved it, newer ones do not.
    missing = [k for k in missing if not k.endswith("position_ids")]
    unexpected = [k for k in unexpected if not k.endswith("position_ids")]
    if missing or unexpected:
        raise SystemExit(f"{dataset}: missing {missing[:5]}, unexpected {unexpected[:5]}")
    encoder.eval()

    labels = list(
        torch.load(
            jit_web / "text_val" / dataset / "drw_weights.pt",
            map_location="cpu",
            weights_only=False,
        )["label_cols"]
    )
    df = pd.read_csv(jit_web / "text_val" / dataset / "txt_val.csv").fillna(0)
    txt_col = next(
        (c for c in df.columns if c.strip().lower() in ("sentence", "report", "text", "caption")),
        "sentence",
    )

    embeds = []
    with torch.no_grad():
        for label in labels:
            sentences = df[df[label] == 1][txt_col].tolist() or [f"Patient has {label}"]
            tok = tokenizer(sentences, return_tensors="pt", padding=True, truncation=True)
            e = encoder(tok["input_ids"], tok["attention_mask"])
            e = e / e.norm(dim=-1, keepdim=True)
            avg = e.mean(dim=0, keepdim=True)
            embeds.append(avg / avg.norm(dim=-1, keepdim=True))
            print(f"  {dataset:8s} {label:28s} {len(sentences):3d} sentences")

    torch.save(
        {"labels": labels, "embeds": torch.cat(embeds, dim=0)},
        OUT / dataset / "text_embeds.pt",
    )
    # The image half alone (~110 MB of the 547 MB), which is all the app loads:
    # a fifth of the upload to a GPU box.
    torch.save(
        {k: v for k, v in weights.items() if k.startswith("vision_model.") or k == "logit_scale"},
        OUT / dataset / "vision.pt",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jit-web", type=Path, required=True, help="JIT-Web checkout")
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(BERT_TYPE)
    tokenizer.model_max_length = 77  # as MedCLIPProcessor sets it
    for dataset in DATASETS:
        build(dataset, args.jit_web, tokenizer)

    # The image encoder's architecture, so the app never has to reach the hub.
    config = AutoConfig.from_pretrained(VIT_TYPE)
    (OUT / "swin_config.json").write_text(json.dumps(config.to_dict(), indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
