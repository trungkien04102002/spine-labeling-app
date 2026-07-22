"""
Grading Models for SPIDER Dataset Transfer Learning.

Contains both Baseline and CBAM models with SPIDER-specific output heads.
Eight SPIDER labels covering disc / vertebra / alignment / endplate categories:
    - pfirrmann:         5 classes (grades 1-5, stored as 0-4)  — disc degeneration
    - modic:             4 classes (types 0-3)                  — vertebra inflammation
    - disc_narrowing:    2 classes (No/Yes)                     — disc structure
    - spondylolisthesis: 2 classes (No/Yes)                     — spinal alignment
    - up_endplate:       2 classes (No/Yes)                     — upper endplate damage
    - low_endplate:      2 classes (No/Yes)                     — lower endplate damage
    - disc_herniation:   2 classes (No/Yes)                     — disc herniation
    - disc_bulging:      2 classes (No/Yes)                     — disc bulging

These models support loading pretrained RSNA weights (backbone + CBAM)
and only retraining the classification heads.

Author: SpineNetV2 Transfer Learning
"""

import os
import glob
import torch
import torch.nn as nn
from typing import List

# Import from baseline
from spinenet.models.grading_baseline import BasicBlock, conv3x3, conv1x1
from spinenet.models.attention import CBAM


# Single source of truth for SPIDER conditions used across this module and
# train_spider.py / spider_dataloader.py. Keep order stable.
SPIDER_CONDITIONS: List[str] = [
    "pfirrmann",
    "modic",
    "disc_narrowing",
    "spondylolisthesis",
    "up_endplate",
    "low_endplate",
    "disc_herniation",
    "disc_bulging",
]
SPIDER_NUM_CLASSES = {
    "pfirrmann": 5,
    "modic": 4,
    "disc_narrowing": 2,
    "spondylolisthesis": 2,
    "up_endplate": 2,
    "low_endplate": 2,
    "disc_herniation": 2,
    "disc_bulging": 2,
}


class GradingModelSPIDERBaseline(nn.Module):
    """
    Baseline model (ResNet34) for SPIDER dataset.

    Output heads (4 representative SPIDER labels):
    - pfirrmann:         5 classes (disc degeneration)
    - modic:             4 classes (vertebra inflammation)
    - disc_narrowing:    2 classes (disc structure)
    - spondylolisthesis: 2 classes (spinal alignment)

    Can load pretrained RSNA backbone weights.
    """

    def __init__(
        self,
        block: nn.Module = BasicBlock,
        layers: List[int] = [3, 4, 6, 3],  # ResNet34
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        norm_layer: nn.Module = None,
    ):
        super(GradingModelSPIDERBaseline, self).__init__()

        if norm_layer is None:
            norm_layer = nn.BatchNorm3d

        self._norm_layer = norm_layer
        self.inplanes = 64
        self.dilation = 1
        self.groups = groups
        self.base_width = width_per_group

        # === BACKBONE (same as RSNA) ===
        self.conv1 = nn.Conv3d(
            1, self.inplanes,
            kernel_size=(3, 7, 7),
            stride=(1, 2, 2),
            padding=(1, 3, 3),
            bias=False
        )
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool3d(
            kernel_size=(1, 3, 3),
            stride=(1, 2, 2),
            padding=(0, 1, 1)
        )

        # ResNet layers
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=1)
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=2)

        # Global average pooling
        self.avgpool = nn.AdaptiveAvgPool3d((1, 1, 1))

        # === CLASSIFICATION HEADS (8 SPIDER labels) ===
        feat_dim = 512 * block.expansion
        self.fc_pfirrmann         = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["pfirrmann"])
        self.fc_modic             = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["modic"])
        self.fc_disc_narrowing    = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["disc_narrowing"])
        self.fc_spondylolisthesis = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["spondylolisthesis"])
        self.fc_up_endplate       = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["up_endplate"])
        self.fc_low_endplate      = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["low_endplate"])
        self.fc_disc_herniation   = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["disc_herniation"])
        self.fc_disc_bulging      = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["disc_bulging"])

        # === INITIALIZATION ===
        self._initialize_weights(zero_init_residual)

    def _make_layer(
        self,
        block: nn.Module,
        planes: int,
        blocks: int,
        stride: int = 1,
        dilate: bool = False
    ) -> nn.Sequential:
        """Create a ResNet layer."""
        norm_layer = self._norm_layer
        downsample = None
        previous_dilation = self.dilation

        if dilate:
            self.dilation *= stride
            stride = 1

        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )

        layers = []
        layers.append(
            block(
                self.inplanes, planes, stride, downsample,
                self.groups, self.base_width, previous_dilation, norm_layer
            )
        )
        self.inplanes = planes * block.expansion

        for _ in range(1, blocks):
            layers.append(
                block(
                    self.inplanes, planes,
                    groups=self.groups,
                    base_width=self.base_width,
                    dilation=self.dilation,
                    norm_layer=norm_layer
                )
            )

        return nn.Sequential(*layers)

    def _initialize_weights(self, zero_init_residual: bool):
        """Initialize model weights."""
        for m in self.modules():
            if isinstance(m, nn.Conv3d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, (nn.BatchNorm3d, nn.GroupNorm)):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

        if zero_init_residual:
            for m in self.modules():
                if isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)

    def forward(self, x: torch.Tensor):
        """
        Forward pass.

        Args:
            x: [B, 1, 9, 112, 224]

        Returns:
            dict with one entry per SPIDER condition (see SPIDER_CONDITIONS).
        """
        # Backbone
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        # Global pooling
        x = self.avgpool(x)
        x = torch.flatten(x, 1)

        return {
            "pfirrmann":         self.fc_pfirrmann(x),
            "modic":             self.fc_modic(x),
            "disc_narrowing":    self.fc_disc_narrowing(x),
            "spondylolisthesis": self.fc_spondylolisthesis(x),
            "up_endplate":       self.fc_up_endplate(x),
            "low_endplate":      self.fc_low_endplate(x),
            "disc_herniation":   self.fc_disc_herniation(x),
            "disc_bulging":      self.fc_disc_bulging(x),
        }

    def load_pretrained_rsna_backbone(self, checkpoint_path: str, strict: bool = False, verbose: bool = True):
        """
        Load pretrained backbone from RSNA model.

        Loads: conv1, bn1, layer1-4, avgpool
        Skips: RSNA classification heads (different output sizes)

        Args:
            checkpoint_path: Path to RSNA checkpoint
            strict: If True, requires exact match
            verbose: Print loading info
        """
        if verbose:
            print(f"  Loading RSNA pretrained backbone from: {checkpoint_path}")

        # Load RSNA checkpoint
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        pretrained_dict = checkpoint.get("model_state_dict", checkpoint)

        # Get current model state
        model_dict = self.state_dict()

        # Filter: only load backbone, skip fc_* heads
        backbone_dict = {}
        for k, v in pretrained_dict.items():
            # Skip RSNA classification heads (fc_spinal_canal, fc_left_foraminal, fc_right_foraminal)
            if k.startswith('fc_'):
                continue
            # Skip CBAM if exists in RSNA checkpoint
            if 'cbam' in k:
                continue
            # Only load if key exists and shape matches
            if k in model_dict and v.shape == model_dict[k].shape:
                backbone_dict[k] = v
            elif verbose and k in model_dict:
                print(f"  Warning: Skipping {k} due to shape mismatch: {v.shape} vs {model_dict[k].shape}")

        if verbose:
            print(f"  Loaded {len(backbone_dict)}/{len(model_dict)} parameters from RSNA")
            print(f"  SPIDER classification heads randomly initialized")

        # Update and load
        model_dict.update(backbone_dict)
        self.load_state_dict(model_dict, strict=strict)

        if verbose:
            print(f"  ✓ RSNA backbone loaded successfully")

    def freeze_backbone(self, freeze: bool = True):
        """Freeze/unfreeze backbone for transfer learning."""
        for name, param in self.named_parameters():
            if not name.startswith('fc_'):
                param.requires_grad = not freeze


class GradingModelSPIDERCBAM(nn.Module):
    """
    CBAM-enhanced model (ResNet34 + CBAM) for SPIDER dataset.

    Output heads:
    - pfirrmann: 5 classes (0-4)
    - spondylolisthesis: 2 classes (0-1)
    - disc_herniation: 2 classes (0-1)

    Can load pretrained RSNA backbone + CBAM weights.
    """

    def __init__(
        self,
        block: nn.Module = BasicBlock,
        layers: List[int] = [3, 4, 6, 3],  # ResNet34
        cbam_reduction: int = 16,
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        norm_layer: nn.Module = None,
    ):
        super(GradingModelSPIDERCBAM, self).__init__()

        if norm_layer is None:
            norm_layer = nn.BatchNorm3d

        self._norm_layer = norm_layer
        self.inplanes = 64
        self.dilation = 1
        self.groups = groups
        self.base_width = width_per_group

        # === BACKBONE (same as RSNA) ===
        self.conv1 = nn.Conv3d(
            1, self.inplanes,
            kernel_size=(3, 7, 7),
            stride=(1, 2, 2),
            padding=(1, 3, 3),
            bias=False
        )
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool3d(
            kernel_size=(1, 3, 3),
            stride=(1, 2, 2),
            padding=(0, 1, 1)
        )

        # ResNet layers
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=1)
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=2)

        # === CBAM ATTENTION MODULES (same as RSNA) ===
        self.cbam1 = CBAM(in_channels=64, reduction=cbam_reduction)
        self.cbam2 = CBAM(in_channels=128, reduction=cbam_reduction)
        self.cbam3 = CBAM(in_channels=256, reduction=cbam_reduction)
        self.cbam4 = CBAM(in_channels=512, reduction=cbam_reduction)

        # Global average pooling
        self.avgpool = nn.AdaptiveAvgPool3d((1, 1, 1))

        # === CLASSIFICATION HEADS (8 SPIDER labels) ===
        feat_dim = 512 * block.expansion
        self.fc_pfirrmann         = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["pfirrmann"])
        self.fc_modic             = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["modic"])
        self.fc_disc_narrowing    = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["disc_narrowing"])
        self.fc_spondylolisthesis = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["spondylolisthesis"])
        self.fc_up_endplate       = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["up_endplate"])
        self.fc_low_endplate      = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["low_endplate"])
        self.fc_disc_herniation   = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["disc_herniation"])
        self.fc_disc_bulging      = nn.Linear(feat_dim, SPIDER_NUM_CLASSES["disc_bulging"])

        # === INITIALIZATION ===
        self._initialize_weights(zero_init_residual)

    def _make_layer(
        self,
        block: nn.Module,
        planes: int,
        blocks: int,
        stride: int = 1,
        dilate: bool = False
    ) -> nn.Sequential:
        """Create a ResNet layer."""
        norm_layer = self._norm_layer
        downsample = None
        previous_dilation = self.dilation

        if dilate:
            self.dilation *= stride
            stride = 1

        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                conv1x1(self.inplanes, planes * block.expansion, stride),
                norm_layer(planes * block.expansion),
            )

        layers = []
        layers.append(
            block(
                self.inplanes, planes, stride, downsample,
                self.groups, self.base_width, previous_dilation, norm_layer
            )
        )
        self.inplanes = planes * block.expansion

        for _ in range(1, blocks):
            layers.append(
                block(
                    self.inplanes, planes,
                    groups=self.groups,
                    base_width=self.base_width,
                    dilation=self.dilation,
                    norm_layer=norm_layer
                )
            )

        return nn.Sequential(*layers)

    def _initialize_weights(self, zero_init_residual: bool):
        """Initialize model weights."""
        for m in self.modules():
            if isinstance(m, nn.Conv3d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, (nn.BatchNorm3d, nn.GroupNorm)):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

        if zero_init_residual:
            for m in self.modules():
                if isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)

    def forward(self, x: torch.Tensor):
        """
        Forward pass with CBAM attention.

        Args:
            x: [B, 1, 9, 112, 224]

        Returns:
            dict with one entry per SPIDER condition (see SPIDER_CONDITIONS).
        """
        # Backbone
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        # ResNet + CBAM
        x = self.layer1(x); x = self.cbam1(x)
        x = self.layer2(x); x = self.cbam2(x)
        x = self.layer3(x); x = self.cbam3(x)
        x = self.layer4(x); x = self.cbam4(x)

        # Global pooling
        x = self.avgpool(x)
        x = torch.flatten(x, 1)

        return {
            "pfirrmann":         self.fc_pfirrmann(x),
            "modic":             self.fc_modic(x),
            "disc_narrowing":    self.fc_disc_narrowing(x),
            "spondylolisthesis": self.fc_spondylolisthesis(x),
            "up_endplate":       self.fc_up_endplate(x),
            "low_endplate":      self.fc_low_endplate(x),
            "disc_herniation":   self.fc_disc_herniation(x),
            "disc_bulging":      self.fc_disc_bulging(x),
        }

    def load_pretrained_rsna_backbone(self, checkpoint_path: str, strict: bool = False, verbose: bool = True):
        """
        Load pretrained backbone + CBAM from RSNA CBAM model.

        Loads: conv1, bn1, layer1-4, cbam1-4, avgpool
        Skips: RSNA classification heads (different output sizes)

        Args:
            checkpoint_path: Path to RSNA CBAM checkpoint
            strict: If True, requires exact match
            verbose: Print loading info
        """
        if verbose:
            print(f"  Loading RSNA pretrained backbone + CBAM from: {checkpoint_path}")

        # Load RSNA CBAM checkpoint
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        pretrained_dict = checkpoint.get("model_state_dict", checkpoint)

        # Get current model state
        model_dict = self.state_dict()

        # Filter: load backbone + CBAM, skip fc_* heads
        backbone_dict = {}
        for k, v in pretrained_dict.items():
            # Skip RSNA classification heads
            if k.startswith('fc_'):
                continue
            # Load if key exists and shape matches
            if k in model_dict and v.shape == model_dict[k].shape:
                backbone_dict[k] = v
            elif verbose and k in model_dict:
                print(f"  Warning: Skipping {k} due to shape mismatch: {v.shape} vs {model_dict[k].shape}")

        if verbose:
            print(f"  Loaded {len(backbone_dict)}/{len(model_dict)} parameters from RSNA")
            print(f"  Backbone + CBAM modules loaded from RSNA training")
            print(f"  SPIDER classification heads randomly initialized")

        # Update and load
        model_dict.update(backbone_dict)
        self.load_state_dict(model_dict, strict=strict)

        if verbose:
            print(f"  ✓ RSNA backbone + CBAM loaded successfully")

    def freeze_backbone(self, freeze: bool = True):
        """Freeze/unfreeze backbone + CBAM for transfer learning."""
        for name, param in self.named_parameters():
            # Keep fc_* trainable, freeze everything else
            if not name.startswith('fc_'):
                param.requires_grad = not freeze


# Test code
if __name__ == "__main__":
    print("="*70)
    print("Testing SPIDER Models")
    print("="*70)

    # Test baseline
    print("\n[1/2] Testing SPIDER Baseline Model...")
    model_baseline = GradingModelSPIDERBaseline()
    model_baseline.eval()

    x = torch.randn(2, 1, 9, 112, 224)
    outputs = model_baseline(x)

    print(f"✓ Baseline model created!")
    print(f"  - Input: {x.shape}")
    print(f"  - Outputs:")
    for key, value in outputs.items():
        print(f"    • {key}: {value.shape}")

    total_params = sum(p.numel() for p in model_baseline.parameters())
    print(f"  - Total parameters: {total_params:,}")

    # Test CBAM
    print("\n[2/2] Testing SPIDER CBAM Model...")
    model_cbam = GradingModelSPIDERCBAM()
    model_cbam.eval()

    outputs = model_cbam(x)

    print(f"✓ CBAM model created!")
    print(f"  - Input: {x.shape}")
    print(f"  - Outputs:")
    for key, value in outputs.items():
        print(f"    • {key}: {value.shape}")

    total_params = sum(p.numel() for p in model_cbam.parameters())
    print(f"  - Total parameters: {total_params:,}")

    print("\n" + "="*70)
    print("✓ All tests passed!")
    print("="*70)
    print("\nBoth models ready for SPIDER transfer learning:")
    print("  - Baseline: ResNet34 backbone")
    print("  - CBAM: ResNet34 + CBAM attention")
    print("  - Both have SPIDER-specific heads (5, 2, 2)")
    print()
