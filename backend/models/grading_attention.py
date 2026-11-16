"""Grading model with CBAM attention: the baseline ResNet34 plus a CBAM block
after each residual stage.
"""

import os
import glob
import torch
import torch.nn as nn
from typing import List

from .grading_baseline import BasicBlock, conv3x3, conv1x1
from .attention import CBAM


class GradingModelWithCBAM(nn.Module):
    """Multi-task IVD grading model: ResNet34 with CBAM after layer1-4.

    Input: ``[B, 1, 9, 112, 224]``.

    Output:
        format='rsna': dict with ``spinal_canal``, ``left_foraminal`` and
        ``right_foraminal``, each ``[B, 3]``.
        format='original': tuple of 11 logit tensors (SpineNet tasks).
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
            format: 'rsna' (3 tasks) or 'original' (11 tasks).
            use_cbam: insert CBAM after each stage; False gives the baseline.
            cbam_reduction: CBAM channel reduction ratio.
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

        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=1)  # stride 1 keeps spatial detail
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=2)

        if self.use_cbam:
            self.cbam1 = CBAM(in_channels=64, reduction=cbam_reduction)
            self.cbam2 = CBAM(in_channels=128, reduction=cbam_reduction)
            self.cbam3 = CBAM(in_channels=256, reduction=cbam_reduction)
            self.cbam4 = CBAM(in_channels=512, reduction=cbam_reduction)

        self.avgpool = nn.AdaptiveAvgPool3d((1, 1, 1))

        if format == 'rsna':
            # 3 tasks, all 3-class (Normal/Mild, Moderate, Severe)
            self.fc_spinal_canal = nn.Linear(512 * block.expansion, 3)
            self.fc_left_foraminal = nn.Linear(512 * block.expansion, 3)
            self.fc_right_foraminal = nn.Linear(512 * block.expansion, 3)
        elif format == 'original':
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
        x = self.conv1(x)       # [B, 64, 9, 56, 112]
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)     # [B, 64, 9, 28, 56]

        x = self.layer1(x)      # [B, 64, 9, 28, 56]
        if self.use_cbam:
            x = self.cbam1(x)

        x = self.layer2(x)      # [B, 128, 9, 28, 56]
        if self.use_cbam:
            x = self.cbam2(x)

        x = self.layer3(x)      # [B, 256, 9, 14, 28]
        if self.use_cbam:
            x = self.cbam3(x)

        x = self.layer4(x)      # [B, 512, 9, 7, 14]
        if self.use_cbam:
            x = self.cbam4(x)

        x = self.avgpool(x)     # [B, 512, 1, 1, 1]
        x = torch.flatten(x, 1) # [B, 512]

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
        """Return the pooled 512-d feature ``[B, 512]`` (the input to the heads)."""
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
        """Load backbone weights from a SpineNet checkpoint.

        Heads and CBAM blocks keep their fresh initialisation; tensors with an
        unknown name or a mismatched shape are skipped.

        Args:
            weights_dir: a ``.pt`` file, or a directory (newest ``*.pt`` is used).
            strict: passed to ``load_state_dict``.
            verbose: print what was loaded.
        """
        if os.path.isdir(weights_dir):
            list_of_pt = glob.glob(os.path.join(weights_dir, "*.pt"))
            if not list_of_pt:
                raise FileNotFoundError(f"No .pt files found in {weights_dir}")
            checkpoint_path = max(list_of_pt, key=os.path.getctime)
        else:
            checkpoint_path = weights_dir

        if verbose:
            print(f"  Loading backbone from: {checkpoint_path}")

        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        pretrained_dict = checkpoint.get("model_weights", checkpoint)

        model_dict = self.state_dict()

        backbone_dict = {}
        for k, v in pretrained_dict.items():
            if k.startswith('fc_'):
                continue
            if 'cbam' in k:
                continue
            if k in model_dict:
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

        model_dict.update(backbone_dict)
        self.load_state_dict(model_dict, strict=strict)

        if verbose:
            print(f"  ✓ Backbone loaded successfully")

    def freeze_backbone(self, freeze: bool = True):
        """Freeze (or unfreeze) the backbone; ``fc_*`` heads and CBAM blocks stay trainable."""
        for name, param in self.named_parameters():
            if not name.startswith('fc_') and 'cbam' not in name:
                param.requires_grad = not freeze


if __name__ == "__main__":
    print("Testing GradingModelWithCBAM...")

    model = GradingModelWithCBAM(format='rsna', use_cbam=True)
    model.eval()

    x = torch.randn(2, 1, 9, 112, 224)
    outputs = model(x)

    print(f"\n✓ Model created successfully!")
    print(f"  - Input shape: {x.shape}")
    print(f"  - Output keys: {list(outputs.keys())}")
    for key, value in outputs.items():
        print(f"  - {key}: {value.shape}")

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\n  - Total parameters: {total_params:,}")
    print(f"  - Trainable parameters: {trainable_params:,}")

    print(f"\nTesting backbone freezing...")
    model.freeze_backbone(freeze=True)
    trainable_params_frozen = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  - After freezing: {trainable_params_frozen:,} trainable")

    print(f"\n✓ All tests passed!")
