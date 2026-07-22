"""
BiomedCLIP Wrapper.

Loads BiomedCLIP from HuggingFace via open_clip, freezes all parameters,
and exposes encode_image and encode_text methods.

Reference:
    Zhang et al. "BiomedCLIP: a multimodal biomedical foundation model
    pretrained from fifteen million scientific image-text pairs" (2023)
    https://huggingface.co/microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Tuple


BIOMEDCLIP_HF_ID = "hf-hub:microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224"


class BiomedCLIPWrapper(nn.Module):
    """
    Frozen BiomedCLIP wrapper for image and text encoding.

    Both image encoder (ViT-B/16) and text encoder (PubMedBERT + text projection)
    are loaded pretrained from HuggingFace and kept FROZEN.

    Image input: 2D RGB tensor [B, 3, 224, 224] (must be normalized per BiomedCLIP)
    Text input: tokenized via accompanying tokenizer
    Output dim: 512

    Usage:
        wrapper = BiomedCLIPWrapper()
        text_embs = wrapper.encode_text(["normal", "severe stenosis"])  # [N, 512]
        slice_emb = wrapper.encode_image(rgb_slice)  # [B, 512]
    """

    EMBED_DIM = 512

    def __init__(self, model_name: str = BIOMEDCLIP_HF_ID, device: str = "cuda"):
        super().__init__()
        try:
            from open_clip import create_model_from_pretrained, get_tokenizer
        except ImportError as e:
            raise ImportError(
                "open_clip_torch required for BiomedCLIP. "
                "Install: pip install open_clip_torch"
            ) from e

        self.model, self.preprocess = create_model_from_pretrained(model_name)
        self.tokenizer = get_tokenizer(model_name)
        self.model = self.model.to(device).eval()

        # Freeze everything
        for p in self.model.parameters():
            p.requires_grad = False

        self._device = device

    @torch.no_grad()
    def encode_text(self, texts: List[str]) -> torch.Tensor:
        """
        Encode list of text strings to [N, 512] L2-normalized embeddings.
        Includes BiomedCLIP's internal text projection (frozen).
        """
        tokens = self.tokenizer(texts).to(self._device)
        embs = self.model.encode_text(tokens)
        return F.normalize(embs, dim=-1)

    @torch.no_grad()
    def encode_image(self, images: torch.Tensor) -> torch.Tensor:
        """
        Encode batch of preprocessed RGB images to [B, 512] L2-normalized embeddings.

        Args:
            images: [B, 3, 224, 224] tensor, already normalized via self.preprocess
        """
        embs = self.model.encode_image(images)
        return F.normalize(embs, dim=-1)

    def preprocess_slice(self, slice_2d: torch.Tensor) -> torch.Tensor:
        """
        Convert grayscale slice [H, W] in [0,1] to BiomedCLIP-ready [3, 224, 224].

        Steps:
        1. Resize to 224x224
        2. Repeat to 3 channels (RGB)
        3. Apply BiomedCLIP-specific normalization

        Args:
            slice_2d: [H, W] grayscale in [0, 1]

        Returns:
            [3, 224, 224] tensor ready for encode_image
        """
        # Resize
        x = slice_2d.unsqueeze(0).unsqueeze(0)  # [1, 1, H, W]
        x = F.interpolate(x, size=(224, 224), mode="bilinear", align_corners=False)
        x = x.squeeze(0).squeeze(0)  # [224, 224]

        # Repeat to 3 channels
        x = x.unsqueeze(0).repeat(3, 1, 1)  # [3, 224, 224]

        # BiomedCLIP normalization (OpenAI CLIP stats)
        mean = torch.tensor([0.48145466, 0.4578275, 0.40821073]).view(3, 1, 1)
        std = torch.tensor([0.26862954, 0.26130258, 0.27577711]).view(3, 1, 1)
        x = (x - mean.to(x.device)) / std.to(x.device)

        return x


if __name__ == "__main__":
    import sys
    print("Testing BiomedCLIPWrapper...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    wrapper = BiomedCLIPWrapper(device=device)

    # Test text encoding
    labels = [
        "normal spinal canal",
        "moderate spinal canal stenosis",
        "severe spinal canal stenosis",
        "disc herniation",
    ]
    text_embs = wrapper.encode_text(labels)
    print(f"\nText embeddings: {text_embs.shape}")
    assert text_embs.shape == (4, 512)
    print(f"  L2 norms: {text_embs.norm(dim=-1)}")

    # Test image encoding
    fake_slice = torch.rand(112, 224)  # grayscale
    rgb = wrapper.preprocess_slice(fake_slice).unsqueeze(0).to(device)
    print(f"\nPreprocessed slice: {rgb.shape}")
    assert rgb.shape == (1, 3, 224, 224)

    img_emb = wrapper.encode_image(rgb)
    print(f"Image embedding: {img_emb.shape}")
    assert img_emb.shape == (1, 512)

    # Test cosine similarity
    sims = img_emb @ text_embs.T
    print(f"Similarities: {sims}")

    # Verify everything frozen
    trainable = sum(p.numel() for p in wrapper.parameters() if p.requires_grad)
    total = sum(p.numel() for p in wrapper.parameters())
    print(f"\nTrainable: {trainable} / {total} (should be 0)")
    assert trainable == 0, "BiomedCLIP must be fully frozen"

    print("\nAll tests passed.")
