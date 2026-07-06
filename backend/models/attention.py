"""
Attention Modules for SpineNetV2.

Implements CBAM (Convolutional Block Attention Module) for 3D medical imaging.

Reference:
    Woo et al. "CBAM: Convolutional Block Attention Module" ECCV 2018
    https://arxiv.org/abs/1807.06521

Author: SpineNetV2 Improved Implementation
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class ChannelAttention(nn.Module):
    """
    Channel Attention Module for CBAM.

    Learns "what" is important by computing attention weights for each channel.
    Uses both max pooling and average pooling to capture different statistics.
    """
    def __init__(self, in_channels: int, reduction: int = 16):
        """
        Args:
            in_channels: Number of input channels
            reduction: Channel reduction ratio for bottleneck (default: 16)
        """
        super(ChannelAttention, self).__init__()

        # Shared MLP: in_channels -> in_channels//reduction -> in_channels
        self.avg_pool = nn.AdaptiveAvgPool3d(1)
        self.max_pool = nn.AdaptiveMaxPool3d(1)

        self.fc = nn.Sequential(
            nn.Conv3d(in_channels, in_channels // reduction, kernel_size=1, bias=False),
            nn.ReLU(inplace=True),
            nn.Conv3d(in_channels // reduction, in_channels, kernel_size=1, bias=False)
        )
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        """
        Args:
            x: Input tensor [B, C, D, H, W]
        Returns:
            Channel attention weights [B, C, 1, 1, 1]
        """
        # Average pooling branch
        avg_out = self.fc(self.avg_pool(x))

        # Max pooling branch
        max_out = self.fc(self.max_pool(x))

        # Combine and apply sigmoid
        out = self.sigmoid(avg_out + max_out)
        return out


class SpatialAttention(nn.Module):
    """
    Spatial Attention Module for CBAM.

    Learns "where" is important by computing attention weights for each spatial location.
    Uses channel-wise max and average pooling followed by convolution.
    """
    def __init__(self, kernel_size: int = 7):
        """
        Args:
            kernel_size: Convolution kernel size (default: 7)
        """
        super(SpatialAttention, self).__init__()

        padding = kernel_size // 2
        self.conv = nn.Conv3d(2, 1, kernel_size=kernel_size, padding=padding, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        """
        Args:
            x: Input tensor [B, C, D, H, W]
        Returns:
            Spatial attention weights [B, 1, D, H, W]
        """
        # Channel-wise max and average pooling
        avg_out = torch.mean(x, dim=1, keepdim=True)  # [B, 1, D, H, W]
        max_out, _ = torch.max(x, dim=1, keepdim=True)  # [B, 1, D, H, W]

        # Concatenate along channel dimension
        x = torch.cat([avg_out, max_out], dim=1)  # [B, 2, D, H, W]

        # Apply convolution and sigmoid
        x = self.conv(x)
        return self.sigmoid(x)


class CBAM(nn.Module):
    """
    Convolutional Block Attention Module (CBAM) for 3D data.

    Sequentially applies channel attention followed by spatial attention.
    Can be inserted after any convolutional layer.

    Example:
        >>> cbam = CBAM(in_channels=256)
        >>> x = torch.randn(2, 256, 9, 28, 56)
        >>> out = cbam(x)  # Same shape as input
    """
    def __init__(self, in_channels: int, reduction: int = 16, kernel_size: int = 7):
        """
        Args:
            in_channels: Number of input channels
            reduction: Channel reduction ratio (default: 16)
            kernel_size: Spatial attention kernel size (default: 7)
        """
        super(CBAM, self).__init__()

        self.channel_attention = ChannelAttention(in_channels, reduction)
        self.spatial_attention = SpatialAttention(kernel_size)

    def forward(self, x):
        """
        Args:
            x: Input tensor [B, C, D, H, W]
        Returns:
            Attention-refined features [B, C, D, H, W]
        """
        # Channel attention
        x = x * self.channel_attention(x)

        # Spatial attention
        x = x * self.spatial_attention(x)

        return x
