"""Baseline grading model: 3D ResNet34 backbone with single linear heads.

The no-attention reference model. Input is a batch of IVD volumes
``[B, 1, 9, 112, 224]``; ``BasicBlock``, ``conv3x3`` and ``conv1x1`` are also
reused by the CBAM variant.
"""

import os
import glob
import torch
import torch.nn as nn
from typing import List, Tuple


def conv3x3(in_planes: int, out_planes: int, stride: int = 1, groups: int = 1, dilation: int = 1):
    """3x3x3 convolution with padding."""
    return nn.Conv3d(
        in_planes,
        out_planes,
        kernel_size=(3, 3, 3),
        stride=(1, stride, stride),  # never downsample the 9-slice depth axis
        padding=(1, dilation, dilation),
        groups=groups,
        bias=False,
        dilation=dilation,
    )


def conv1x1(in_planes: int, out_planes: int, stride: int = 1):
    """1x1x1 convolution."""
    return nn.Conv3d(
        in_planes,
        out_planes,
        kernel_size=(1, 1, 1),
        stride=(1, stride, stride),
        padding=(0, 0, 0),
        bias=False,
    )


class BasicBlock(nn.Module):
    """
    Basic ResNet block for 3D convolutions.

    Structure:
        x -> conv3x3 -> BN -> ReLU -> conv3x3 -> BN -> (+residual) -> ReLU
    """
    expansion = 1

    def __init__(
        self,
        inplanes: int,
        planes: int,
        stride: int = 1,
        downsample: nn.Module = None,
        groups: int = 1,
        base_width: int = 64,
        dilation: int = 1,
        norm_layer: nn.Module = None,
    ):
        super(BasicBlock, self).__init__()

        if norm_layer is None:
            norm_layer = nn.BatchNorm3d

        if groups != 1 or base_width != 64:
            raise ValueError("BasicBlock only supports groups=1 and base_width=64")

        if dilation > 1:
            raise NotImplementedError("Dilation > 1 not supported in BasicBlock")

        self.conv1 = conv3x3(inplanes, planes, stride)
        self.bn1 = norm_layer(planes)
        self.relu = nn.ReLU(inplace=True)

        self.conv2 = conv3x3(planes, planes)
        self.bn2 = norm_layer(planes)

        self.downsample = downsample
        self.stride = stride

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Input tensor [B, C, D, H, W]

        Returns:
            Output tensor [B, C', D, H', W']
        """
        identity = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            identity = self.downsample(x)

        out += identity
        out = self.relu(out)

        return out


class GradingModelBaseline(nn.Module):
    """Multi-task IVD grading model: ResNet34 backbone, one linear head per task.

    Input: ``[B, 1, 9, 112, 224]``.

    Output:
        format='original': tuple of 11 logit tensors (SpineNet tasks).
        format='rsna': dict with ``spinal_canal``, ``left_foraminal`` and
        ``right_foraminal``, each ``[B, 3]``.
    """

    def __init__(
        self,
        block: nn.Module = BasicBlock,
        layers: List[int] = [3, 4, 6, 3],  # ResNet34 configuration
        num_classes: int = 2,  # Not used (for compatibility)
        format: str = 'original',  # 'original' or 'rsna'
        zero_init_residual: bool = False,
        groups: int = 1,
        width_per_group: int = 64,
        norm_layer: nn.Module = None,
    ):
        super(GradingModelBaseline, self).__init__()

        if norm_layer is None:
            norm_layer = nn.BatchNorm3d

        self._norm_layer = norm_layer
        self.inplanes = 64
        self.dilation = 1
        self.groups = groups
        self.base_width = width_per_group
        self.format = format

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

        self.avgpool = nn.AdaptiveAvgPool3d((1, 1, 1))

        if format == 'original':
            self.fc_pf = nn.Linear(512 * block.expansion, 5)   # Pfirrmann
            self.fc_nar = nn.Linear(512 * block.expansion, 4)  # Narrowing
            self.fc_ccs = nn.Linear(512 * block.expansion, 4)  # Central Canal Stenosis
            self.fc_spn = nn.Linear(512 * block.expansion, 3)  # Spondylolisthesis
            self.fc_ued = nn.Linear(512 * block.expansion, 2)  # Upper Endplate Defect
            self.fc_led = nn.Linear(512 * block.expansion, 2)  # Lower Endplate Defect
            self.fc_umc = nn.Linear(512 * block.expansion, 2)  # Upper Marrow Changes
            self.fc_lmc = nn.Linear(512 * block.expansion, 2)  # Lower Marrow Changes
            self.fc_fsl = nn.Linear(512 * block.expansion, 2)  # Foraminal Stenosis Left
            self.fc_fsr = nn.Linear(512 * block.expansion, 2)  # Foraminal Stenosis Right
            self.fc_hrn = nn.Linear(512 * block.expansion, 2)  # Herniation
        elif format == 'rsna':
            # 3 tasks, all 3-class (Normal/Mild, Moderate, Severe)
            self.fc_spinal_canal = nn.Linear(512 * block.expansion, 3)
            self.fc_left_foraminal = nn.Linear(512 * block.expansion, 3)
            self.fc_right_foraminal = nn.Linear(512 * block.expansion, 3)
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
        Forward pass.

        Args:
            x: Input volume [B, 1, 9, 112, 224]

        Returns:
            If format='original': Tuple of 11 tensors (one per task)
            If format='rsna': Dictionary with 3 keys
        """
        x = self.conv1(x)       # [B, 64, 9, 56, 112]
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)     # [B, 64, 9, 28, 56]

        x = self.layer1(x)      # [B, 64, 9, 28, 56]
        x = self.layer2(x)      # [B, 128, 9, 28, 56] (stride=1)
        x = self.layer3(x)      # [B, 256, 9, 14, 28]
        x = self.layer4(x)      # [B, 512, 9, 7, 14]

        x = self.avgpool(x)     # [B, 512, 1, 1, 1]
        x = torch.flatten(x, 1) # [B, 512]

        if self.format == 'original':
            x_pf = self.fc_pf(x)    # [B, 5]
            x_nar = self.fc_nar(x)  # [B, 4]
            x_ccs = self.fc_ccs(x)  # [B, 4]
            x_spn = self.fc_spn(x)  # [B, 3]
            x_ued = self.fc_ued(x)  # [B, 2]
            x_led = self.fc_led(x)  # [B, 2]
            x_umc = self.fc_umc(x)  # [B, 2]
            x_lmc = self.fc_lmc(x)  # [B, 2]
            x_fsl = self.fc_fsl(x)  # [B, 2]
            x_fsr = self.fc_fsr(x)  # [B, 2]
            x_hrn = self.fc_hrn(x)  # [B, 2]
            return (x_pf, x_nar, x_ccs, x_spn, x_ued, x_led,
                    x_umc, x_lmc, x_fsl, x_fsr, x_hrn)
        else:  # format == 'rsna'
            out_spinal_canal = self.fc_spinal_canal(x)      # [B, 3]
            out_left_foraminal = self.fc_left_foraminal(x)  # [B, 3]
            out_right_foraminal = self.fc_right_foraminal(x)# [B, 3]
            return {
                'spinal_canal': out_spinal_canal,
                'left_foraminal': out_left_foraminal,
                'right_foraminal': out_right_foraminal
            }

    def load_weights(self, save_path: str, verbose: bool = True):
        """Load the newest ``*.pt`` checkpoint (key ``model_weights``) in ``save_path``."""
        if os.path.isdir(save_path):
            list_of_pt = glob.glob(save_path + "/*.pt")
            latest_pt = max(list_of_pt, key=os.path.getctime)
            checkpoint = torch.load(latest_pt, map_location="cpu", weights_only=False)
            self.load_state_dict(checkpoint["model_weights"])
            start_epoch = checkpoint.get("epoch_no", 0) + 1
            if verbose:
                print(f"==> Loaded baseline model trained for {start_epoch} epochs from {latest_pt}")
        else:
            raise FileNotFoundError(f"Save path {save_path} not found")

    def finetune(self, reset_weights: bool = True):
        """Freeze everything except the ``fc_*`` heads, optionally re-initialising them."""
        for param in self.parameters():
            param.requires_grad = False

        for name, module in self.named_children():
            if name.startswith('fc_'):
                for param in module.parameters():
                    param.requires_grad = True
                if reset_weights:
                    module.reset_parameters()

    def load_pretrained_backbone(self, weights_dir: str, strict: bool = False, verbose: bool = True):
        """Load backbone weights from a SpineNet checkpoint, leaving the heads untouched.

        Tensors with an unknown name or a mismatched shape are skipped.

        Args:
            weights_dir: a ``.pt`` file, or a directory (newest ``*.pt`` is used).
            strict: passed to ``load_state_dict``.
            verbose: print what was loaded.
        """
        import glob

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
            print(f"  Classification heads will be randomly initialized")

        model_dict.update(backbone_dict)
        self.load_state_dict(model_dict, strict=strict)

        if verbose:
            print(f"  ✓ Backbone loaded successfully")

    def freeze_backbone(self, freeze: bool = True):
        """Freeze (or unfreeze) every non-head parameter; ``fc_*`` heads stay trainable."""
        for name, param in self.named_parameters():
            if not name.startswith('fc_'):
                param.requires_grad = not freeze


if __name__ == "__main__":
    print("Testing GradingModelBaseline...\n")

    print("="*60)
    print("TEST 1: Original Format (11 tasks)")
    print("="*60)
    model_original = GradingModelBaseline(format='original')
    print(f"✓ Model created (format='original')")

    total_params = sum(p.numel() for p in model_original.parameters())
    print(f"Total parameters: {total_params:,}")

    batch_size = 2
    x = torch.randn(batch_size, 1, 9, 112, 224)
    print(f"Input shape: {x.shape}")

    outputs = model_original(x)
    print(f"Output type: {type(outputs)} (Tuple)")
    print(f"Number of tasks: {len(outputs)}")

    expected_classes = [5, 4, 4, 3, 2, 2, 2, 2, 2, 2, 2]
    for i, (output, num_classes) in enumerate(zip(outputs, expected_classes)):
        assert output.shape == (batch_size, num_classes), \
            f"Output {i} shape mismatch! Expected ({batch_size}, {num_classes}), got {output.shape}"
        print(f"  Task {i+1}: {output.shape} ✓")

    print("\n" + "="*60)
    print("TEST 2: RSNA 2024 Format (3 tasks)")
    print("="*60)
    model_rsna = GradingModelBaseline(format='rsna')
    print(f"✓ Model created (format='rsna')")

    total_params_rsna = sum(p.numel() for p in model_rsna.parameters())
    print(f"Total parameters: {total_params_rsna:,}")

    outputs_rsna = model_rsna(x)
    print(f"Output type: {type(outputs_rsna)} (Dictionary)")
    print(f"Output keys: {list(outputs_rsna.keys())}")

    for key, value in outputs_rsna.items():
        assert value.shape == (batch_size, 3), \
            f"Output {key} shape mismatch! Expected ({batch_size}, 3), got {value.shape}"
        print(f"  {key}: {value.shape} ✓")

    print("\n" + "="*60)
    print("✓ All tests passed!")
    print("="*60)
    print(f"\nParameter difference: {total_params - total_params_rsna:,} fewer params in RSNA format")
