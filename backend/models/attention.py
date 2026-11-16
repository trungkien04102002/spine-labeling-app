"""3D CBAM (Convolutional Block Attention Module).

Reference: Woo et al., "CBAM: Convolutional Block Attention Module", ECCV 2018,
https://arxiv.org/abs/1807.06521
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class ChannelAttention(nn.Module):
    """Per-channel attention weights from average- and max-pooled descriptors
    passed through a shared bottleneck MLP."""
    def __init__(self, in_channels: int, reduction: int = 16):
        super(ChannelAttention, self).__init__()

        self.avg_pool = nn.AdaptiveAvgPool3d(1)
        self.max_pool = nn.AdaptiveMaxPool3d(1)

        self.fc = nn.Sequential(
            nn.Conv3d(in_channels, in_channels // reduction, kernel_size=1, bias=False),
            nn.ReLU(inplace=True),
            nn.Conv3d(in_channels // reduction, in_channels, kernel_size=1, bias=False)
        )
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        """Return weights ``[B, C, 1, 1, 1]`` for input ``[B, C, D, H, W]``."""
        avg_out = self.fc(self.avg_pool(x))
        max_out = self.fc(self.max_pool(x))
        out = self.sigmoid(avg_out + max_out)
        return out


class SpatialAttention(nn.Module):
    """Per-voxel attention weights from channel-wise mean and max maps,
    followed by a single convolution."""
    def __init__(self, kernel_size: int = 7):
        super(SpatialAttention, self).__init__()

        padding = kernel_size // 2
        self.conv = nn.Conv3d(2, 1, kernel_size=kernel_size, padding=padding, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        """Return weights ``[B, 1, D, H, W]`` for input ``[B, C, D, H, W]``."""
        avg_out = torch.mean(x, dim=1, keepdim=True)  # [B, 1, D, H, W]
        max_out, _ = torch.max(x, dim=1, keepdim=True)  # [B, 1, D, H, W]

        x = torch.cat([avg_out, max_out], dim=1)  # [B, 2, D, H, W]

        x = self.conv(x)
        return self.sigmoid(x)


class CBAM(nn.Module):
    """Channel attention followed by spatial attention; output shape equals input shape."""
    def __init__(self, in_channels: int, reduction: int = 16, kernel_size: int = 7):
        super(CBAM, self).__init__()

        self.channel_attention = ChannelAttention(in_channels, reduction)
        self.spatial_attention = SpatialAttention(kernel_size)

    def forward(self, x):
        x = x * self.channel_attention(x)
        x = x * self.spatial_attention(x)

        return x
