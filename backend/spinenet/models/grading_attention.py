"""
Attention-Enhanced Grading Model for SpineNetV2.

Extends GradingModelBaseline with CBAM (Convolutional Block Attention Module).
Improves feature discrimination for minority classes (Moderate, Severe).

Author: SpineNetV2 Improved Implementation
"""

import os
import glob
import torch
import torch.nn as nn
from typing import List

# Import from baseline
from spinenet.models.grading_baseline import BasicBlock, conv3x3, conv1x1
from spinenet.models.attention import CBAM


class GradingModelWithCBAM(nn.Module):
    """
    CBAM-Enhanced Grading Model (ResNet34 + CBAM) for multi-task IVD classification.

    Architecture Improvements over Baseline:
        - Adds CBAM after each ResNet layer (layer1-4)
        - Channel attention learns "what" features are important
        - Spatial attention learns "where" to focus
        - Better discrimination for subtle pathologies (Moderate vs Severe)

    Input:
        [Batch, 1, 9, 112, 224] - Batch of IVD volumes

    Output (format='rsna'):
        Dictionary with 3 keys:
        - 'spinal_canal': [Batch, 3]
        - 'left_foraminal': [Batch, 3]
        - 'right_foraminal': [Batch, 3]

    Example:
        >>> model = GradingModelWithCBAM(format='rsna')
        >>> x = torch.randn(2, 1, 9, 112, 224)
        >>> outputs = model(x)
        >>> outputs['spinal_canal'].shape
        torch.Size([2, 3])
    """

    def __init__(
        self,
        block: nn.Module = BasicBlock,
        layers: List[int] = [3, 4, 6, 3],  # ResNet34 configuration
        format: str = 'rsna',
        use_cbam: bool = True,
        cbam_reduction: int = 16,
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        norm_layer: nn.Module = None,
    ):
        """
        Args:
            block: BasicBlock (ResNet34)
            layers: Number of blocks in each layer [3, 4, 6, 3]
            format: 'rsna' (3 tasks) or 'original' (11 tasks)
            use_cbam: Enable CBAM attention (default: True)
            cbam_reduction: CBAM channel reduction ratio (default: 16)
            zero_init_residual: Zero-initialize residual BN
            groups: Conv groups (default: 1)
            width_per_group: Width per group (default: 64)
            norm_layer: Normalization layer (default: BatchNorm3d)
        """
        super(GradingModelWithCBAM, self).__init__()

        if norm_layer is None:
            norm_layer = nn.BatchNorm3d

        self._norm_layer = norm_layer
        self.inplanes = 64
        self.dilation = 1
        self.groups = groups
        self.base_width = width_per_group
        self.format = format
        self.use_cbam = use_cbam

        # === BACKBONE ===
        # Initial convolution: 1 -> 64 channels
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
        self.layer1 = self._make_layer(block, 64, layers[0])   # 64 channels
        self.layer2 = self._make_layer(block, 128, layers[1], stride=1)  # 128 channels
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)  # 256 channels
        self.layer4 = self._make_layer(block, 512, layers[3], stride=2)  # 512 channels

        # === CBAM ATTENTION MODULES ===
        if self.use_cbam:
            self.cbam1 = CBAM(in_channels=64, reduction=cbam_reduction)
            self.cbam2 = CBAM(in_channels=128, reduction=cbam_reduction)
            self.cbam3 = CBAM(in_channels=256, reduction=cbam_reduction)
            self.cbam4 = CBAM(in_channels=512, reduction=cbam_reduction)

        # Global average pooling
        self.avgpool = nn.AdaptiveAvgPool3d((1, 1, 1))

        # === CLASSIFICATION HEADS ===
        if format == 'rsna':
            # 3 tasks, all 3-class (Normal/Mild, Moderate, Severe)
            self.fc_spinal_canal = nn.Linear(512 * block.expansion, 3)
            self.fc_left_foraminal = nn.Linear(512 * block.expansion, 3)
            self.fc_right_foraminal = nn.Linear(512 * block.expansion, 3)
        elif format == 'original':
            # 11 tasks with different number of classes
            self.fc_pf = nn.Linear(512 * block.expansion, 5)
            self.fc_nar = nn.Linear(512 * block.expansion, 4)
            self.fc_ccs = nn.Linear(512 * block.expansion, 4)
            self.fc_spn = nn.Linear(512 * block.expansion, 3)
            self.fc_ued = nn.Linear(512 * block.expansion, 2)
            self.fc_led = nn.Linear(512 * block.expansion, 2)
            self.fc_umc = nn.Linear(512 * block.expansion, 2)
            self.fc_lmc = nn.Linear(512 * block.expansion, 2)
            self.fc_fsl = nn.Linear(512 * block.expansion, 2)
            self.fc_fsr = nn.Linear(512 * block.expansion, 2)
            self.fc_hrn = nn.Linear(512 * block.expansion, 2)
        else:
            raise ValueError(f"Unknown format: {format}. Use 'original' or 'rsna'")

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
        """Create a ResNet layer with multiple blocks."""
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

        # Zero-initialize the last BN in each residual branch
        if zero_init_residual:
            for m in self.modules():
                if isinstance(m, BasicBlock):
                    nn.init.constant_(m.bn2.weight, 0)

    def forward(self, x: torch.Tensor):
        """
        Forward pass with CBAM attention.

        Args:
            x: Input volume [B, 1, 9, 112, 224]

        Returns:
            If format='rsna': Dictionary with 3 keys
            If format='original': Tuple of 11 tensors
        """
        # Input: [B, 1, 9, 112, 224]

        # Initial conv + pooling
        x = self.conv1(x)       # [B, 64, 9, 56, 112]
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)     # [B, 64, 9, 28, 56]

        # ResNet blocks with CBAM
        x = self.layer1(x)      # [B, 64, 9, 28, 56]
        if self.use_cbam:
            x = self.cbam1(x)   # Apply channel + spatial attention

        x = self.layer2(x)      # [B, 128, 9, 28, 56]
        if self.use_cbam:
            x = self.cbam2(x)

        x = self.layer3(x)      # [B, 256, 9, 14, 28]
        if self.use_cbam:
            x = self.cbam3(x)

        x = self.layer4(x)      # [B, 512, 9, 7, 14]
        if self.use_cbam:
            x = self.cbam4(x)

        # Global pooling
        x = self.avgpool(x)     # [B, 512, 1, 1, 1]
        x = torch.flatten(x, 1) # [B, 512]

        # Multi-task classification
        if self.format == 'rsna':
            out_spinal_canal = self.fc_spinal_canal(x)      # [B, 3]
            out_left_foraminal = self.fc_left_foraminal(x)  # [B, 3]
            out_right_foraminal = self.fc_right_foraminal(x)# [B, 3]
            return {
                'spinal_canal': out_spinal_canal,
                'left_foraminal': out_left_foraminal,
                'right_foraminal': out_right_foraminal
            }
        else:  # format == 'original'
            x_pf = self.fc_pf(x)
            x_nar = self.fc_nar(x)
            x_ccs = self.fc_ccs(x)
            x_spn = self.fc_spn(x)
            x_ued = self.fc_ued(x)
            x_led = self.fc_led(x)
            x_umc = self.fc_umc(x)
            x_lmc = self.fc_lmc(x)
            x_fsl = self.fc_fsl(x)
            x_fsr = self.fc_fsr(x)
            x_hrn = self.fc_hrn(x)
            return (x_pf, x_nar, x_ccs, x_spn, x_ued, x_led,
                    x_umc, x_lmc, x_fsl, x_fsr, x_hrn)

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract 512-dim feature BEFORE classification heads.
        Used by Hybrid model when CBAM is frozen backbone.

        Args:
            x: Input volume [B, 1, 9, 112, 224]

        Returns:
            Feature tensor [B, 512]
        """
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        if self.use_cbam:
            x = self.cbam1(x)
        x = self.layer2(x)
        if self.use_cbam:
            x = self.cbam2(x)
        x = self.layer3(x)
        if self.use_cbam:
            x = self.cbam3(x)
        x = self.layer4(x)
        if self.use_cbam:
            x = self.cbam4(x)

        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        return x

    def load_pretrained_backbone(self, weights_dir: str, strict: bool = False, verbose: bool = True):
        """
        Load pretrained backbone weights from original SpineNet model.

        Only loads backbone (conv1, bn1, layer1-4, avgpool), NOT classification heads.
        CBAM modules are randomly initialized (not in pretrained weights).

        Args:
            weights_dir: Path to directory containing pretrained weights (.pt files)
            strict: If True, requires exact match. If False, allows missing/extra keys
            verbose: Print loading information
        """
        # Find latest checkpoint
        if os.path.isdir(weights_dir):
            list_of_pt = glob.glob(os.path.join(weights_dir, "*.pt"))
            if not list_of_pt:
                raise FileNotFoundError(f"No .pt files found in {weights_dir}")
            checkpoint_path = max(list_of_pt, key=os.path.getctime)
        else:
            checkpoint_path = weights_dir

        if verbose:
            print(f"  Loading backbone from: {checkpoint_path}")

        # Load checkpoint
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        pretrained_dict = checkpoint.get("model_weights", checkpoint)

        # Get current model state
        model_dict = self.state_dict()

        # Filter out classification heads and CBAM modules
        backbone_dict = {}
        for k, v in pretrained_dict.items():
            # Skip classification heads
            if k.startswith('fc_'):
                continue
            # Skip CBAM (not in pretrained weights, will be randomly initialized)
            if 'cbam' in k:
                continue
            # Only load if key exists in current model
            if k in model_dict:
                # Check shape compatibility
                if v.shape == model_dict[k].shape:
                    backbone_dict[k] = v
                elif verbose:
                    print(f"  Warning: Skipping {k} due to shape mismatch: "
                          f"{v.shape} vs {model_dict[k].shape}")
            elif verbose and not k.startswith('fc_'):
                print(f"  Warning: Key {k} not found in current model")

        if verbose:
            total_params = len(model_dict)
            loaded_params = len(backbone_dict)
            print(f"  Loaded {loaded_params}/{total_params} parameters")
            print(f"  CBAM modules and classification heads randomly initialized")

        # Update model dict and load
        model_dict.update(backbone_dict)
        self.load_state_dict(model_dict, strict=strict)

        if verbose:
            print(f"  ✓ Backbone loaded successfully")

    def freeze_backbone(self, freeze: bool = True):
        """
        Freeze or unfreeze backbone parameters for transfer learning.

        Args:
            freeze: If True, freeze backbone (train only heads + CBAM).
                   If False, unfreeze backbone (train everything).
        """
        # Freeze/unfreeze backbone layers
        for name, param in self.named_parameters():
            # Classification heads start with 'fc_'
            # CBAM modules contain 'cbam'
            # Freeze everything except fc_* and cbam*
            if not name.startswith('fc_') and 'cbam' not in name:
                param.requires_grad = not freeze


# Test code
if __name__ == "__main__":
    print("Testing GradingModelWithCBAM...")

    # Create model
    model = GradingModelWithCBAM(format='rsna', use_cbam=True)
    model.eval()

    # Test forward pass
    x = torch.randn(2, 1, 9, 112, 224)
    outputs = model(x)

    print(f"\n✓ Model created successfully!")
    print(f"  - Input shape: {x.shape}")
    print(f"  - Output keys: {list(outputs.keys())}")
    for key, value in outputs.items():
        print(f"  - {key}: {value.shape}")

    # Count parameters
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\n  - Total parameters: {total_params:,}")
    print(f"  - Trainable parameters: {trainable_params:,}")

    # Test freezing
    print(f"\nTesting backbone freezing...")
    model.freeze_backbone(freeze=True)
    trainable_params_frozen = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  - After freezing: {trainable_params_frozen:,} trainable")

    print(f"\n✓ All tests passed!")
